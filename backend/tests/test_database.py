"""Tests for KubeWatch database persistence, models, relationships, and transactions.

Includes unit tests that run entirely in-memory (SQLite) without needing an external
database, plus optional integration tests for a real local PostgreSQL instance.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Generator

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import check_db_health, get_db, session_scope
from app.models.incident import Incident, IncidentEvidence
from app.models.recommendation import ResourceRecommendation
from app.models.rule import DetectionRule


# ---------------------------------------------------------------------------
# Unit Test Fixtures (SQLite in-memory, no external database required)
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_engine():
    """In-memory SQLite engine with static pool for isolated test execution."""
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
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    """Provide a clean session bound to the in-memory SQLite database."""
    session_factory = sessionmaker(
        bind=sqlite_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Unit Tests: Models & Constraints
# ---------------------------------------------------------------------------

class TestIncidentModels:
    """Validate Incident and IncidentEvidence creation, relations, and cascading."""

    def test_create_incident_with_all_fields(self, db_session: Session) -> None:
        """Verify an incident is created with all required fields and defaults."""
        now = datetime.now(timezone.utc)
        incident = Incident(
            cluster_id="minikube-dev",
            resource_type="Pod",
            namespace="production",
            resource_name="payment-service-abc12",
            rule_identifier="pod-crashlooping",
            severity="critical",
            title="Pod payment-service-abc12 is CrashLooping",
            description="Container exited with code 137 (OOMKilled).",
            first_observed_at=now,
            last_observed_at=now,
            status="active",
        )
        db_session.add(incident)
        db_session.commit()

        # Query back
        stmt = select(Incident).where(Incident.resource_name == "payment-service-abc12")
        stored = db_session.scalar(stmt)
        assert stored is not None
        assert stored.id is not None
        assert len(stored.id) == 36  # UUID string format
        assert stored.cluster_id == "minikube-dev"
        assert stored.severity == "critical"
        assert stored.status == "active"
        assert stored.resolution_time is None
        assert stored.created_at is not None

    def test_incident_evidence_relationship_and_cascade(self, db_session: Session) -> None:
        """Verify evidence is attached to incident and cascades upon deletion."""
        now = datetime.now(timezone.utc)
        incident = Incident(
            cluster_id="minikube-dev",
            resource_type="Deployment",
            namespace="default",
            resource_name="web-frontend",
            rule_identifier="deployment-replicas-unavailable",
            severity="warning",
            title="Deployment web-frontend has 0/3 available replicas",
            description="Pods failing readiness probe.",
            first_observed_at=now,
            last_observed_at=now,
            status="active",
        )
        db_session.add(incident)
        db_session.commit()

        evidence1 = IncidentEvidence(
            incident_id=incident.id,
            evidence_type="k8s_event",
            summary="Readiness probe failed: HTTP 503 Service Unavailable",
            observation_time=now,
            source_metadata={"probe_port": 8080, "http_code": 503},
        )
        evidence2 = IncidentEvidence(
            incident_id=incident.id,
            evidence_type="metric_breach",
            summary="Available replicas reached 0 below threshold of 1",
            observation_time=now,
            source_metadata={"ready_replicas": 0, "desired_replicas": 3},
        )
        db_session.add_all([evidence1, evidence2])
        db_session.commit()

        # Query incident with relationship
        reloaded = db_session.get(Incident, incident.id)
        assert reloaded is not None
        assert len(reloaded.evidence) == 2
        assert reloaded.evidence[0].source_metadata["desired_replicas"] in (3, None)

        # Deleting parent incident must delete evidence entries (cascade="all, delete-orphan")
        db_session.delete(reloaded)
        db_session.commit()

        evidence_count = db_session.scalar(
            select(IncidentEvidence).where(IncidentEvidence.incident_id == incident.id)
        )
        assert evidence_count is None

    def test_incident_resolution_update(self, db_session: Session) -> None:
        """Verify transitioning an incident to resolved updates resolution_time."""
        now = datetime.now(timezone.utc)
        incident = Incident(
            cluster_id="test-cluster",
            resource_type="Node",
            namespace=None,  # Nodes are cluster-scoped
            resource_name="minikube-m01",
            rule_identifier="node-memory-pressure",
            severity="warning",
            title="Node minikube-m01 MemoryPressure",
            description="Available memory below 10%",
            first_observed_at=now,
            last_observed_at=now,
            status="active",
        )
        db_session.add(incident)
        db_session.commit()

        # Resolve incident
        resolved_time = datetime.now(timezone.utc)
        incident.status = "resolved"
        incident.resolution_time = resolved_time
        db_session.commit()

        updated = db_session.get(Incident, incident.id)
        assert updated is not None
        assert updated.status == "resolved"
        assert updated.resolution_time == resolved_time


class TestResourceRecommendationModel:
    """Validate ResourceRecommendation schema, JSON summaries, and review status."""

    def test_create_recommendation(self, db_session: Session) -> None:
        """Verify recommendation stores workload, JSON summaries, and narrative."""
        rec = ResourceRecommendation(
            cluster_id="default",
            namespace="production",
            workload_type="Deployment",
            workload_name="api-gateway",
            container_name="gateway",
            recommendation_type="cpu_request",
            observation_window="7d",
            current_configuration={"cpu_request": "500m", "cpu_limit": "1000m"},
            measured_usage={"p95_cpu": "85m", "p99_cpu": "120m", "max_cpu": "180m"},
            recommendation_text=(
                "Reduce CPU request from 500m to 150m. Measured p95 peak is 85m. "
                "Frees 350m of allocatable cluster capacity."
            ),
            review_status="pending",
        )
        db_session.add(rec)
        db_session.commit()

        loaded = db_session.get(ResourceRecommendation, rec.id)
        assert loaded is not None
        assert loaded.workload_name == "api-gateway"
        assert loaded.current_configuration["cpu_request"] == "500m"
        assert loaded.measured_usage["p95_cpu"] == "85m"
        assert loaded.review_status == "pending"

        # Update review status
        loaded.review_status = "applied"
        db_session.commit()

        updated = db_session.get(ResourceRecommendation, rec.id)
        assert updated is not None
        assert updated.review_status == "applied"


class TestDetectionRuleModel:
    """Validate DetectionRule schema, configuration, and state."""

    def test_create_detection_rule(self, db_session: Session) -> None:
        """Verify detection rule stores slug ID, threshold config, and active toggle."""
        rule = DetectionRule(
            id="high-cpu-throttling",
            name="High CPU Throttling Rate",
            description="Triggers when container throttled periods exceed 25% over 5m window.",
            severity="warning",
            enabled=True,
            threshold_config={
                "metric": "container_cpu_cfs_throttled_periods_total",
                "threshold_percentage": 25.0,
                "window": "5m",
            },
        )
        db_session.add(rule)
        db_session.commit()

        loaded = db_session.get(DetectionRule, "high-cpu-throttling")
        assert loaded is not None
        assert loaded.name == "High CPU Throttling Rate"
        assert loaded.enabled is True
        assert loaded.threshold_config["threshold_percentage"] == 25.0

        # Toggle disabled
        loaded.enabled = False
        db_session.commit()
        assert db_session.get(DetectionRule, "high-cpu-throttling").enabled is False


# ---------------------------------------------------------------------------
# Unit Tests: Transactions & Session Scope
# ---------------------------------------------------------------------------

class TestTransactionsAndSessionScope:
    """Validate transaction commit on success and automatic rollback on failure."""

    def test_session_scope_commit_on_success(self, sqlite_engine) -> None:
        """Operations within session_scope are committed when no error occurs."""
        rule_id = f"test-rule-{uuid.uuid4().hex[:8]}"
        with session_scope(sqlite_engine) as session:
            rule = DetectionRule(
                id=rule_id,
                name="Test Rule Success",
                severity="info",
                threshold_config={},
            )
            session.add(rule)

        # Verify persisted via separate session
        with session_scope(sqlite_engine) as session:
            stored = session.get(DetectionRule, rule_id)
            assert stored is not None
            assert stored.name == "Test Rule Success"

    def test_session_scope_rollback_on_exception(self, sqlite_engine) -> None:
        """Operations within session_scope are rolled back if an error is raised."""
        rule_id = f"test-rule-{uuid.uuid4().hex[:8]}"
        with pytest.raises(RuntimeError, match="Simulated application failure"):
            with session_scope(sqlite_engine) as session:
                rule = DetectionRule(
                    id=rule_id,
                    name="Test Rule Rollback",
                    severity="warning",
                    threshold_config={},
                )
                session.add(rule)
                raise RuntimeError("Simulated application failure")

        # Verify NOT persisted
        with session_scope(sqlite_engine) as session:
            stored = session.get(DetectionRule, rule_id)
            assert stored is None

    def test_check_db_health(self, sqlite_engine) -> None:
        """check_db_health returns connected=True on valid engine."""
        health = check_db_health(sqlite_engine)
        assert health["status"] == "ok"
        assert health["connected"] is True


# ---------------------------------------------------------------------------
# Optional Integration Tests: Local PostgreSQL Instance
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestPostgreSqlIntegration:
    """Optional tests against the real local PostgreSQL instance.
    
    Skipped automatically if DATABASE_URL is unavailable or Postgres is down.
    Never resets or destroys existing production/development tables.
    """

    @pytest.fixture
    def pg_session(self) -> Generator[Session, None, None]:
        db_url = os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://kubewatch:local_dev_only_change_me@127.0.0.1:5432/kubewatch",
        )
        try:
            from app.db.session import create_db_engine
            engine = create_db_engine(db_url)
            with engine.connect() as conn:
                conn.execute(select(1))
        except Exception as exc:
            pytest.skip(f"Local PostgreSQL not reachable at {db_url}: {exc}")

        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
        session = factory()
        try:
            yield session
        finally:
            session.close()

    def test_postgres_incident_crud(self, pg_session: Session) -> None:
        """Verify incident insertion, querying, and deletion in real PostgreSQL."""
        test_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        incident = Incident(
            id=test_id,
            cluster_id="local-integration-test",
            resource_type="Pod",
            namespace="kube-system",
            resource_name=f"test-pod-{test_id[:8]}",
            rule_identifier="test-integration-rule",
            severity="info",
            title="Integration Test Incident",
            description="Testing live PostgreSQL persistence.",
            first_observed_at=now,
            last_observed_at=now,
            status="active",
        )
        pg_session.add(incident)
        pg_session.commit()

        # Query back
        stored = pg_session.get(Incident, test_id)
        assert stored is not None
        assert stored.cluster_id == "local-integration-test"

        # Clean up inserted test record without touching other data
        pg_session.delete(stored)
        pg_session.commit()
        assert pg_session.get(Incident, test_id) is None
