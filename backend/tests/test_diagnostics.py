"""Deterministic unit tests for KubeWatch diagnostics engine, rules, and incident API.

Covers:
- Healthy conditions
- Trigger conditions
- Recovery conditions
- Missing metrics and source failure handling
- Repeated evaluation and duplicate prevention (fingerprinting)
- Evidence generation and explainability structure
- Incident API operations (list, filter, get, acknowledge, resolve)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.diagnostics.base import EvaluationContext, utc_now
from app.diagnostics.engine import DiagnosticsEngine
from app.diagnostics.rules.deployment_availability import DeploymentAvailabilityRule
from app.diagnostics.rules.memory_utilization import HighMemoryUtilizationRule
from app.diagnostics.rules.node_pressure import NodePressureRule
from app.diagnostics.rules.pending_pod import PendingPodRule
from app.diagnostics.rules.restart_activity import IncreasedRestartActivityRule
from app.diagnostics.scheduler import DiagnosticsScheduler
from app.main import create_app
from app.models.incident import Incident, IncidentEvidence
from app.schemas.models import (
    ContainerInfo,
    ContainerResources,
    DeploymentCondition,
    DeploymentInfo,
    NodeCondition,
    NodeInfo,
    NodeResources,
    PodInfo,
)


# ---------------------------------------------------------------------------
# Database Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def in_memory_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db_session(in_memory_engine) -> Generator[Session, None, None]:
    session_factory = sessionmaker(bind=in_memory_engine, autoflush=False, autocommit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Test Helpers
# ---------------------------------------------------------------------------

def make_pod(
    name: str = "test-pod",
    namespace: str = "default",
    phase: str = "Running",
    node_name: str | None = "node-1",
    created_at: datetime | None = None,
    containers: list[ContainerInfo] | None = None,
) -> PodInfo:
    return PodInfo(
        name=name,
        namespace=namespace,
        phase=phase,
        node_name=node_name,
        restart_count=sum(c.restart_count for c in (containers or [])),
        containers=containers or [
            ContainerInfo(
                name="app",
                image="nginx:latest",
                ready=True,
                restart_count=0,
                state="running",
            )
        ],
        created_at=created_at or utc_now(),
    )


def make_node(
    name: str = "node-1",
    status: str = "Ready",
    conditions: list[NodeCondition] | None = None,
) -> NodeInfo:
    return NodeInfo(
        name=name,
        status=status,
        roles=["worker"],
        capacity=NodeResources(cpu="4", memory="16Gi"),
        allocatable=NodeResources(cpu="3800m", memory="15Gi"),
        conditions=conditions or [
            NodeCondition(type="Ready", status="True"),
            NodeCondition(type="MemoryPressure", status="False"),
            NodeCondition(type="DiskPressure", status="False"),
            NodeCondition(type="PIDPressure", status="False"),
        ],
        created_at=utc_now(),
    )


def make_deployment(
    name: str = "web-service",
    namespace: str = "default",
    replicas: int = 3,
    available_replicas: int = 3,
    ready_replicas: int = 3,
    unavailable_replicas: int = 0,
) -> DeploymentInfo:
    return DeploymentInfo(
        name=name,
        namespace=namespace,
        replicas=replicas,
        available_replicas=available_replicas,
        ready_replicas=ready_replicas,
        unavailable_replicas=unavailable_replicas,
        strategy="RollingUpdate",
        conditions=[DeploymentCondition(type="Available", status="True")],
        created_at=utc_now(),
    )


# ---------------------------------------------------------------------------
# Rule 1: Increased Restart Activity Tests
# ---------------------------------------------------------------------------

class TestIncreasedRestartActivityRule:
    """Tests for container restart activity rule."""

    def test_healthy_pod_no_incident(self) -> None:
        rule = IncreasedRestartActivityRule()
        pod = make_pod(containers=[ContainerInfo(name="app", image="img", ready=True, restart_count=0, state="running")])
        ctx = EvaluationContext(pods=[pod])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 0

    def test_trigger_warning_on_restart_threshold(self) -> None:
        rule = IncreasedRestartActivityRule()
        pod = make_pod(containers=[ContainerInfo(name="app", image="img", ready=True, restart_count=5, state="running")])
        ctx = EvaluationContext(pods=[pod])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.rule_identifier == "container-restart-activity"
        assert c.severity == "warning"
        assert c.resource_name == "test-pod"
        assert len(c.evidence) == 1
        assert c.evidence[0].evidence_type == "container_state"
        assert c.evidence[0].measured_value["restart_count"] == 5

    def test_trigger_critical_on_high_restarts_or_oom(self) -> None:
        rule = IncreasedRestartActivityRule()
        pod = make_pod(containers=[
            ContainerInfo(name="worker", image="img", ready=False, restart_count=16, state="terminated: OOMKilled (137)")
        ])
        ctx = EvaluationContext(pods=[pod])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        assert candidates[0].severity == "critical"

    def test_trigger_on_crashloop_state_even_under_threshold(self) -> None:
        rule = IncreasedRestartActivityRule()
        pod = make_pod(containers=[
            ContainerInfo(name="auth", image="img", ready=False, restart_count=2, state="waiting: CrashLoopBackOff")
        ])
        ctx = EvaluationContext(pods=[pod])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        assert candidates[0].severity == "warning"


# ---------------------------------------------------------------------------
# Rule 2: Pending Pod Rule Tests
# ---------------------------------------------------------------------------

class TestPendingPodRule:
    """Tests for pods stuck in Pending phase."""

    def test_healthy_running_pod_no_incident(self) -> None:
        rule = PendingPodRule()
        pod = make_pod(phase="Running")
        ctx = EvaluationContext(pods=[pod])
        assert len(rule.evaluate(ctx)) == 0

    def test_recent_pending_pod_within_grace_period_no_incident(self) -> None:
        rule = PendingPodRule()
        recent_time = utc_now() - timedelta(seconds=60)
        pod = make_pod(phase="Pending", created_at=recent_time)
        ctx = EvaluationContext(pods=[pod])
        assert len(rule.evaluate(ctx)) == 0

    def test_pending_pod_exceeding_threshold_triggers_warning(self) -> None:
        rule = PendingPodRule()
        old_time = utc_now() - timedelta(seconds=350)
        pod = make_pod(phase="Pending", created_at=old_time)
        ctx = EvaluationContext(pods=[pod])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.rule_identifier == "pod-pending-duration"
        assert c.severity == "warning"
        assert c.evidence[0].measured_value["elapsed_seconds"] >= 350

    def test_pending_pod_exceeding_critical_threshold(self) -> None:
        rule = PendingPodRule()
        very_old_time = utc_now() - timedelta(seconds=1000)
        pod = make_pod(phase="Pending", created_at=very_old_time)
        ctx = EvaluationContext(pods=[pod])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        assert candidates[0].severity == "critical"


# ---------------------------------------------------------------------------
# Rule 3: Deployment Availability Deficit Tests
# ---------------------------------------------------------------------------

class TestDeploymentAvailabilityRule:
    """Tests for deployment replica availability deficit."""

    def test_healthy_deployment_no_incident(self) -> None:
        rule = DeploymentAvailabilityRule()
        deploy = make_deployment(replicas=3, available_replicas=3)
        ctx = EvaluationContext(deployments=[deploy])
        assert len(rule.evaluate(ctx)) == 0

    def test_scaled_to_zero_no_incident(self) -> None:
        rule = DeploymentAvailabilityRule()
        deploy = make_deployment(replicas=0, available_replicas=0)
        ctx = EvaluationContext(deployments=[deploy])
        assert len(rule.evaluate(ctx)) == 0

    def test_partial_replica_deficit_triggers_warning(self) -> None:
        rule = DeploymentAvailabilityRule()
        deploy = make_deployment(replicas=3, available_replicas=2, unavailable_replicas=1)
        ctx = EvaluationContext(deployments=[deploy])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        c = candidates[0]
        assert c.rule_identifier == "deployment-replicas-unavailable"
        assert c.severity == "warning"
        assert c.evidence[0].measured_value["deficit"] == 1

    def test_zero_available_replicas_triggers_critical(self) -> None:
        rule = DeploymentAvailabilityRule()
        deploy = make_deployment(replicas=3, available_replicas=0, unavailable_replicas=3)
        child_pod = make_pod(name="web-service-7f8d-x", phase="Pending")
        ctx = EvaluationContext(deployments=[deploy], pods=[child_pod])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        assert candidates[0].severity == "critical"
        # Should cite correlated child pod
        assert len(candidates[0].evidence) == 2


# ---------------------------------------------------------------------------
# Rule 4: High Memory Utilization Tests
# ---------------------------------------------------------------------------

class TestHighMemoryUtilizationRule:
    """Tests for container memory utilization relative to limit."""

    def test_container_without_limit_skipped(self) -> None:
        rule = HighMemoryUtilizationRule()
        pod = make_pod(containers=[
            ContainerInfo(name="app", image="img", resources=ContainerResources(memory_limit=None))
        ])
        ctx = EvaluationContext(pods=[pod], container_memory_bytes={("default", "test-pod", "app"): 500 * 1024 * 1024})
        assert len(rule.evaluate(ctx)) == 0

    def test_missing_prometheus_metrics_skipped_without_error(self) -> None:
        rule = HighMemoryUtilizationRule()
        pod = make_pod(containers=[
            ContainerInfo(name="app", image="img", resources=ContainerResources(memory_limit="512Mi"))
        ])
        # Prometheus metric empty
        ctx = EvaluationContext(pods=[pod], container_memory_bytes={})
        assert len(rule.evaluate(ctx)) == 0

    def test_prometheus_unavailable_source_skipped(self) -> None:
        rule = HighMemoryUtilizationRule()
        pod = make_pod(containers=[
            ContainerInfo(name="app", image="img", resources=ContainerResources(memory_limit="512Mi"))
        ])
        ctx = EvaluationContext(
            pods=[pod],
            container_memory_bytes={("default", "test-pod", "app"): 500 * 1024 * 1024},
            unavailable_sources={"prometheus"},
        )
        assert len(rule.evaluate(ctx)) == 0

    def test_memory_utilization_trigger_warning_and_critical(self) -> None:
        rule = HighMemoryUtilizationRule()
        limit_bytes = 100 * 1024 * 1024  # 100 MiB

        # 88% -> warning
        pod = make_pod(containers=[
            ContainerInfo(name="cache", image="redis", resources=ContainerResources(memory_limit="100Mi"))
        ])
        ctx = EvaluationContext(
            pods=[pod],
            container_memory_bytes={("default", "test-pod", "cache"): 88 * 1024 * 1024},
        )
        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        assert candidates[0].severity == "warning"
        assert candidates[0].evidence[0].measured_value["utilization_percent"] == 88.0

        # 96% -> critical
        ctx.container_memory_bytes[("default", "test-pod", "cache")] = 96 * 1024 * 1024
        crit_candidates = rule.evaluate(ctx)
        assert len(crit_candidates) == 1
        assert crit_candidates[0].severity == "critical"


# ---------------------------------------------------------------------------
# Rule 5: Node Pressure Condition Tests
# ---------------------------------------------------------------------------

class TestNodePressureRule:
    """Tests for node pressure and NotReady states."""

    def test_healthy_node_no_incident(self) -> None:
        rule = NodePressureRule()
        node = make_node(status="Ready")
        ctx = EvaluationContext(nodes=[node])
        assert len(rule.evaluate(ctx)) == 0

    def test_node_memory_pressure_triggers_critical(self) -> None:
        rule = NodePressureRule()
        node = make_node(
            status="Ready",
            conditions=[
                NodeCondition(type="Ready", status="True"),
                NodeCondition(type="MemoryPressure", status="True", reason="KubeletHasInsufficientMemory"),
            ],
        )
        pod = make_pod(name="api-pod", node_name=node.name)
        ctx = EvaluationContext(nodes=[node], pods=[pod])

        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        assert candidates[0].severity == "critical"
        assert candidates[0].rule_identifier == "node-pressure-condition"
        # Should cite correlated scheduled pods
        assert len(candidates[0].evidence) == 2

    def test_node_disk_pressure_triggers_warning(self) -> None:
        rule = NodePressureRule()
        node = make_node(
            status="Ready",
            conditions=[
                NodeCondition(type="Ready", status="True"),
                NodeCondition(type="DiskPressure", status="True", reason="KubeletHasDiskPressure"),
            ],
        )
        ctx = EvaluationContext(nodes=[node])
        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        assert candidates[0].severity == "warning"

    def test_node_not_ready_triggers_critical(self) -> None:
        rule = NodePressureRule()
        node = make_node(status="NotReady")
        ctx = EvaluationContext(nodes=[node])
        candidates = rule.evaluate(ctx)
        assert len(candidates) == 1
        assert candidates[0].severity == "critical"


# ---------------------------------------------------------------------------
# Diagnostics Engine: Deduplication, Persistence & Recovery Tests
# ---------------------------------------------------------------------------

class TestDiagnosticsEnginePersistenceAndLifecycle:
    """Validate DiagnosticsEngine persistence, deduplication, and recovery logic."""

    def test_repeated_evaluation_does_not_duplicate_incident(self, db_session: Session) -> None:
        """Subsequent evaluations update existing incident and append evidence."""
        engine = DiagnosticsEngine(settings=MagicMock())
        rule = IncreasedRestartActivityRule()
        engine._rules = [rule]

        pod = make_pod(containers=[
            ContainerInfo(name="app", image="img", ready=True, restart_count=6, state="running")
        ])
        ctx = EvaluationContext(pods=[pod], now=utc_now())

        # First evaluation: creates new incident
        candidates1 = engine.run_rules(ctx)
        assert len(candidates1) == 1
        res1 = engine.persist_evaluation(db_session, ctx, candidates1)
        assert res1["persisted_new"] == 1
        assert res1["updated_existing"] == 0

        # Query incident
        stmt = select(Incident).where(Incident.resource_name == "test-pod")
        stored = db_session.scalar(stmt)
        assert stored is not None
        initial_id = stored.id
        assert len(stored.evidence) == 1

        # Second evaluation (condition still present, 7 restarts)
        pod.containers[0].restart_count = 7
        later_ctx = EvaluationContext(pods=[pod], now=utc_now() + timedelta(minutes=1))
        candidates2 = engine.run_rules(later_ctx)
        res2 = engine.persist_evaluation(db_session, later_ctx, candidates2)

        assert res2["persisted_new"] == 0
        assert res2["updated_existing"] == 1

        # Verify ID remained identical (deduplicated) and evidence was appended
        all_incidents = db_session.scalars(select(Incident)).all()
        assert len(all_incidents) == 1
        assert all_incidents[0].id == initial_id
        assert len(all_incidents[0].evidence) == 2

    def test_auto_recovery_when_condition_clears(self, db_session: Session) -> None:
        """When a pending pod transitions to Running, the incident is resolved."""
        engine = DiagnosticsEngine(settings=MagicMock())
        rule = PendingPodRule()
        engine._rules = [rule]

        # Trigger incident: pod in Pending for 400s
        old_time = utc_now() - timedelta(seconds=400)
        pod = make_pod(phase="Pending", created_at=old_time)
        ctx = EvaluationContext(pods=[pod], now=utc_now())
        candidates = engine.run_rules(ctx)
        assert len(candidates) == 1
        res1 = engine.persist_evaluation(db_session, ctx, candidates)
        assert res1["persisted_new"] == 1

        stored = db_session.scalar(select(Incident).where(Incident.resource_name == "test-pod"))
        assert stored is not None
        assert stored.status == "active"

        # Condition resolves: pod transitions to Running phase
        running_pod = make_pod(phase="Running", created_at=old_time)
        recovery_ctx = EvaluationContext(pods=[running_pod], now=utc_now() + timedelta(minutes=2))
        healthy_candidates = engine.run_rules(recovery_ctx)
        assert len(healthy_candidates) == 0

        res2 = engine.persist_evaluation(db_session, recovery_ctx, healthy_candidates)
        assert res2["auto_resolved"] == 1

        db_session.refresh(stored)
        assert stored.status == "resolved"
        assert stored.resolution_time is not None

    def test_auto_recovery_when_deployment_deficit_resolves(self, db_session: Session) -> None:
        """When unavailable replicas return to 0, deployment incident is resolved."""
        engine = DiagnosticsEngine(settings=MagicMock())
        rule = DeploymentAvailabilityRule()
        engine._rules = [rule]

        # Trigger: 1/3 available
        deploy = make_deployment(replicas=3, available_replicas=1, unavailable_replicas=2)
        ctx = EvaluationContext(deployments=[deploy], now=utc_now())
        candidates = engine.run_rules(ctx)
        engine.persist_evaluation(db_session, ctx, candidates)

        stored = db_session.scalar(select(Incident).where(Incident.resource_name == "web-service"))
        assert stored is not None
        assert stored.status == "active"

        # Recovery: 3/3 available
        healthy_deploy = make_deployment(replicas=3, available_replicas=3, unavailable_replicas=0)
        rec_ctx = EvaluationContext(deployments=[healthy_deploy], now=utc_now() + timedelta(minutes=1))
        healthy_candidates = engine.run_rules(rec_ctx)
        assert len(healthy_candidates) == 0

        res = engine.persist_evaluation(db_session, rec_ctx, healthy_candidates)
        assert res["auto_resolved"] == 1
        db_session.refresh(stored)
        assert stored.status == "resolved"

    def test_auto_recovery_when_node_pressure_clears(self, db_session: Session) -> None:
        """When a node's pressure conditions clear, the incident is resolved."""
        engine = DiagnosticsEngine(settings=MagicMock())
        rule = NodePressureRule()
        engine._rules = [rule]

        # Trigger MemoryPressure
        pressured_node = make_node(
            name="node-1",
            conditions=[NodeCondition(type="Ready", status="True"), NodeCondition(type="MemoryPressure", status="True")],
        )
        ctx = EvaluationContext(nodes=[pressured_node], now=utc_now())
        candidates = engine.run_rules(ctx)
        engine.persist_evaluation(db_session, ctx, candidates)

        stored = db_session.scalar(select(Incident).where(Incident.resource_name == "node-1"))
        assert stored is not None
        assert stored.status == "active"

        # Recovery: pressure cleared
        healthy_node = make_node(name="node-1", status="Ready")
        rec_ctx = EvaluationContext(nodes=[healthy_node], now=utc_now() + timedelta(minutes=1))
        healthy_candidates = engine.run_rules(rec_ctx)
        assert len(healthy_candidates) == 0

        res = engine.persist_evaluation(db_session, rec_ctx, healthy_candidates)
        assert res["auto_resolved"] == 1
        db_session.refresh(stored)
        assert stored.status == "resolved"

    def test_auto_recovery_when_crashing_pod_is_removed(self, db_session: Session) -> None:
        """When a crashing pod is deleted/replaced, the incident is resolved."""
        engine = DiagnosticsEngine(settings=MagicMock())
        rule = IncreasedRestartActivityRule()
        engine._rules = [rule]

        # Trigger CrashLoop
        pod = make_pod(name="crashing-pod", containers=[
            ContainerInfo(name="app", image="img", ready=False, restart_count=8, state="waiting: CrashLoopBackOff")
        ])
        ctx = EvaluationContext(pods=[pod], now=utc_now())
        candidates = engine.run_rules(ctx)
        engine.persist_evaluation(db_session, ctx, candidates)

        stored = db_session.scalar(select(Incident).where(Incident.resource_name == "crashing-pod"))
        assert stored is not None
        assert stored.status == "active"

        # Replacement pod created, old crashing-pod removed from cluster
        replacement_pod = make_pod(name="replacement-pod", containers=[
            ContainerInfo(name="app", image="img", ready=True, restart_count=0, state="running")
        ])
        rec_ctx = EvaluationContext(pods=[replacement_pod], now=utc_now() + timedelta(minutes=1))
        candidates = engine.run_rules(rec_ctx)
        res = engine.persist_evaluation(db_session, rec_ctx, candidates)
        assert res["auto_resolved"] == 1

        db_session.refresh(stored)
        assert stored.status == "resolved"

    def test_missing_prometheus_metrics_does_not_resolve_incident(self, db_session: Session) -> None:
        """A temporary metrics outage must NOT resolve an active memory incident."""
        engine = DiagnosticsEngine(settings=MagicMock())
        rule = HighMemoryUtilizationRule()
        engine._rules = [rule]

        pod = make_pod(containers=[
            ContainerInfo(name="app", image="img", resources=ContainerResources(memory_limit="100Mi"))
        ])
        ctx = EvaluationContext(
            pods=[pod],
            container_memory_bytes={("default", "test-pod", "app"): 90 * 1024 * 1024},
            now=utc_now(),
        )
        candidates = engine.run_rules(ctx)
        engine.persist_evaluation(db_session, ctx, candidates)

        stored = db_session.scalar(select(Incident).where(Incident.rule_identifier == "container-memory-high-utilization"))
        assert stored is not None
        assert stored.status == "active"

        # Next sweep: Prometheus is offline
        outage_ctx = EvaluationContext(
            pods=[pod],
            container_memory_bytes={},
            unavailable_sources={"prometheus"},
            now=utc_now() + timedelta(minutes=1),
        )
        outage_candidates = engine.run_rules(outage_ctx)
        res = engine.persist_evaluation(db_session, outage_ctx, outage_candidates)

        assert res["auto_resolved"] == 0
        db_session.refresh(stored)
        # MUST remain active!
        assert stored.status == "active"
        assert stored.resolution_time is None


# ---------------------------------------------------------------------------
# Diagnostics Scheduler Tests
# ---------------------------------------------------------------------------

class TestDiagnosticsScheduler:
    """Validate scheduler concurrency control and lifecycle."""

    @pytest.mark.asyncio
    async def test_scheduler_lock_prevents_overlapping_sweeps(self) -> None:
        settings = MagicMock()
        settings.poll_interval_seconds = 60
        scheduler = DiagnosticsScheduler(
            settings=settings,
            k8s_service=MagicMock(),
            prom_service=MagicMock(),
        )

        # Acquire lock artificially
        await scheduler._scan_lock.acquire()
        try:
            res = await scheduler.run_single_sweep()
            assert res["status"] == "skipped"
            assert res["reason"] == "scan_in_progress"
        finally:
            scheduler._scan_lock.release()

    @pytest.mark.asyncio
    async def test_scheduler_start_and_stop_cleanly(self) -> None:
        settings = MagicMock()
        settings.poll_interval_seconds = 60
        scheduler = DiagnosticsScheduler(
            settings=settings,
            k8s_service=MagicMock(),
            prom_service=MagicMock(),
        )
        scheduler._run_loop = AsyncMock()  # Mock continuous loop

        scheduler.start()
        assert scheduler.is_running is True

        await scheduler.stop()
        assert scheduler.is_running is False


# ---------------------------------------------------------------------------
# Incidents API Endpoint Tests
# ---------------------------------------------------------------------------

class TestIncidentsApi:
    """Validate /api/v1/incidents and /api/incidents endpoints."""

    @pytest.fixture
    def app_client(self, in_memory_engine) -> TestClient:
        app = create_app(lifespan_handler=None)

        def override_get_db():
            session_factory = sessionmaker(bind=in_memory_engine, autoflush=False, autocommit=False)
            session = session_factory()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app)

    def test_list_and_filter_incidents(self, app_client: TestClient, db_session: Session) -> None:
        """Test listing, filtering by status and severity, and ordering."""
        now = utc_now()
        inc1 = Incident(
            id=str(uuid.uuid4()),
            cluster_id="default",
            resource_type="Pod",
            namespace="production",
            resource_name="order-service",
            rule_identifier="container-restart-activity",
            severity="critical",
            title="Pod order-service CrashLooping",
            first_observed_at=now - timedelta(hours=1),
            last_observed_at=now,
            status="active",
        )
        inc2 = Incident(
            id=str(uuid.uuid4()),
            cluster_id="default",
            resource_type="Deployment",
            namespace="default",
            resource_name="web-frontend",
            rule_identifier="deployment-replicas-unavailable",
            severity="warning",
            title="Deployment web-frontend deficit",
            first_observed_at=now - timedelta(hours=2),
            last_observed_at=now - timedelta(minutes=5),
            status="resolved",
            resolution_time=now,
        )
        db_session.add_all([inc1, inc2])
        db_session.commit()

        # List all
        resp = app_client.get("/api/incidents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["data"]) == 2
        # Critical should appear before warning
        assert data["data"][0]["severity"] == "critical"

        # Filter by status=active
        resp_active = app_client.get("/api/incidents?status=active")
        assert resp_active.status_code == 200
        active_data = resp_active.json()["data"]
        assert len(active_data) == 1
        assert active_data[0]["resource_name"] == "order-service"

        # Verify frontend aliases exist in response
        assert "rule_name" in active_data[0]
        assert "message" in active_data[0]
        assert "observed_at" in active_data[0]

    def test_get_incident_details_with_evidence(self, app_client: TestClient, db_session: Session) -> None:
        now = utc_now()
        inc_id = str(uuid.uuid4())
        inc = Incident(
            id=inc_id,
            cluster_id="default",
            resource_type="Node",
            resource_name="worker-01",
            rule_identifier="node-pressure-condition",
            severity="critical",
            title="Node worker-01 MemoryPressure",
            first_observed_at=now,
            last_observed_at=now,
            status="active",
        )
        ev = IncidentEvidence(
            incident_id=inc_id,
            evidence_type="node_condition",
            summary="Node asserted MemoryPressure=True",
            observation_time=now,
            source_metadata={"condition": "MemoryPressure"},
        )
        db_session.add_all([inc, ev])
        db_session.commit()

        resp = app_client.get(f"/api/incidents/{inc_id}")
        assert resp.status_code == 200
        body = resp.json()["data"]
        assert body["id"] == inc_id
        assert len(body["evidence"]) == 1
        assert body["evidence"][0]["evidence_type"] == "node_condition"

    def test_acknowledge_and_resolve_incident_lifecycle(self, app_client: TestClient, db_session: Session) -> None:
        now = utc_now()
        inc_id = str(uuid.uuid4())
        inc = Incident(
            id=inc_id,
            cluster_id="default",
            resource_type="Pod",
            resource_name="cart-svc",
            rule_identifier="container-restart-activity",
            severity="warning",
            title="Pod cart-svc restarting",
            first_observed_at=now,
            last_observed_at=now,
            status="active",
        )
        db_session.add(inc)
        db_session.commit()

        # 1. Acknowledge
        ack_resp = app_client.post(f"/api/incidents/{inc_id}/acknowledge")
        assert ack_resp.status_code == 200
        assert ack_resp.json()["data"]["status"] == "acknowledged"

        # 2. Resolve
        res_resp = app_client.post(f"/api/incidents/{inc_id}/resolve")
        assert res_resp.status_code == 200
        assert res_resp.json()["data"]["status"] == "resolved"
        assert res_resp.json()["data"]["resolution_time"] is not None

        # 3. Cannot acknowledge resolved incident
        re_ack = app_client.post(f"/api/incidents/{inc_id}/acknowledge")
        assert re_ack.status_code == 400
