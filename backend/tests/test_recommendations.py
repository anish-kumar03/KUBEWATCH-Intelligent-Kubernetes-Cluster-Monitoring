"""Deterministic tests for KubeWatch resource recommendation engine.

Covers:
- Statistical calculations (p95, averages, peaks, duration, data completeness).
- Edge cases (missing data, short duration, low sample count, unconfigured limits/requests).
- Heuristic rules (CPU underutilization, memory underutilization, memory limit risk, insufficient data).
- Workload aggregation and fingerprint stability.
- Database persistence and review status lifecycle.
- REST API endpoints and schema serialization.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Generator, List

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import create_app
from app.models.recommendation import ResourceRecommendation
from app.recommendations.calculator import (
    MetricStatistics,
    RecommendationCandidate,
    WorkloadResourceSpec,
    calculate_metric_statistics,
    evaluate_cpu_underutilization,
    evaluate_high_memory_limit_utilization,
    evaluate_insufficient_historical_data,
    evaluate_memory_underutilization,
    format_cpu_millicores,
    format_memory_bytes,
)
from app.recommendations.config import RecommendationConfig
from app.recommendations.engine import RecommendationEngine
from app.schemas.models import (
    ContainerInfo,
    ContainerResources,
    DeploymentInfo,
    MetricDataPoint,
    MetricSeries,
    MetricsResult,
    PodInfo,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sqlite_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(sqlite_engine) -> Generator[Session, None, None]:
    factory = sessionmaker(bind=sqlite_engine, autoflush=False, autocommit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api_client(db_session: Session) -> Generator[TestClient, None, None]:
    test_app = create_app(lifespan_handler=None)
    test_app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(test_app) as client:
        yield client
    test_app.dependency_overrides.clear()


@pytest.fixture
def default_config() -> RecommendationConfig:
    return RecommendationConfig()


# ---------------------------------------------------------------------------
# 1. Statistical Calculations Tests
# ---------------------------------------------------------------------------

class TestStatisticalCalculations:
    """Validate mathematical calculations, sample completeness, and duration requirements."""

    def test_empty_samples_marked_insufficient(self, default_config: RecommendationConfig) -> None:
        """Zero samples must be flagged as insufficient and never treated as zero usage."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)
        stats = calculate_metric_statistics([], start, now, default_config)

        assert stats.sample_count == 0
        assert stats.is_sufficient is False
        assert stats.avg_value is None
        assert stats.peak_value is None
        assert stats.p95_value is None
        assert "Zero metric samples" in (stats.insufficiency_reason or "")

    def test_short_duration_marked_insufficient(self, default_config: RecommendationConfig) -> None:
        """Window shorter than min_observation_hours (6h) is flagged insufficient."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=2)  # Only 2 hours
        data = [0.1, 0.2, 0.15, 0.25, 0.18, 0.22, 0.19, 0.21, 0.2, 0.17, 0.23, 0.16]
        stats = calculate_metric_statistics(data, start, now, default_config)

        assert stats.is_sufficient is False
        assert stats.duration_hours == 2.0
        assert "shorter than the required minimum" in (stats.insufficiency_reason or "")

    def test_low_sample_count_marked_insufficient(self, default_config: RecommendationConfig) -> None:
        """Duration is 24h but sample count is below min_samples_for_evaluation (12)."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)
        data = [0.1, 0.2, 0.15]  # Only 3 samples across 24h
        stats = calculate_metric_statistics(data, start, now, default_config)

        assert stats.is_sufficient is False
        assert "Sample count" in (stats.insufficiency_reason or "")

    def test_low_completeness_ratio_marked_insufficient(self, default_config: RecommendationConfig) -> None:
        """Samples collected are fewer than 50% of expected sampling frequency."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=10)
        # At 300s step, 10h expects ~120 samples. Providing only 25 samples is ~20% completeness.
        data = [0.1] * 25
        stats = calculate_metric_statistics(data, start, now, default_config)

        assert stats.is_sufficient is False
        assert stats.completeness_percent < 50.0
        assert "Data completeness" in (stats.insufficiency_reason or "")

    def test_sufficient_telemetry_computes_statistics_and_p95(self, default_config: RecommendationConfig) -> None:
        """Full 24h observation window with >= 20 samples accurately computes p95, peak, and average."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)
        # Generate 200 samples with values from 0.05 to 0.50
        data = [0.1 + (i % 20) * 0.01 for i in range(200)]  # 0.10 to 0.29
        stats = calculate_metric_statistics(data, start, now, default_config)

        assert stats.is_sufficient is True
        assert stats.sample_count == 200
        assert stats.avg_value is not None and 0.18 <= stats.avg_value <= 0.21
        assert stats.peak_value == 0.29
        assert stats.p95_value is not None
        assert 0.27 <= stats.p95_value <= 0.29

    def test_p95_suppressed_when_sample_count_under_p95_threshold(self, default_config: RecommendationConfig) -> None:
        """p95 should be None when sample count is between 12 and 19 (min_samples_for_p95=20)."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=6)  # 6h window
        # 15 samples: satisfies min_samples_for_evaluation (12) but < min_samples_for_p95 (20)
        data = [0.2] * 15
        cfg = default_config.model_copy(update={"min_observation_hours": 6.0, "step_seconds": 1200})
        stats = calculate_metric_statistics(data, start, now, cfg)

        assert stats.is_sufficient is True
        assert stats.sample_count == 15
        assert stats.p95_value is None
        assert stats.peak_value == 0.2


# ---------------------------------------------------------------------------
# 2. Heuristic Evaluator Tests
# ---------------------------------------------------------------------------

class TestHeuristicEvaluators:
    """Validate individual recommendation rules."""

    def test_cpu_underutilization_triggered(self, default_config: RecommendationConfig) -> None:
        """Container with 1000m request consuming only 100m (10% < 25%) triggers right-sizing."""
        spec = WorkloadResourceSpec(
            container_name="web",
            cpu_request_str="1000m",
            cpu_request_millicores=1000,
        )
        stats = MetricStatistics(
            sample_count=100,
            duration_hours=24.0,
            avg_value=0.08,
            p95_value=0.10,  # 100m (10% utilization)
            peak_value=0.15,
            is_sufficient=True,
        )

        rec = evaluate_cpu_underutilization(
            cluster_id="prod-1",
            namespace="default",
            workload_type="Deployment",
            workload_name="web-service",
            spec=spec,
            cpu_stats=stats,
            config=default_config,
        )

        assert rec is not None
        assert rec.recommendation_type == "cpu_underutilization"
        # 100m * 1.25 headroom = 125m recommended target
        assert rec.current_configuration["recommended_spec"]["cpu_request"] == "125m"
        assert rec.measured_usage["freed_cpu_millicores"] == 875
        assert "Cost Disclaimer" in rec.recommendation_text
        assert "Frees 875m of allocatable node CPU" in rec.measured_usage["resource_reduction_summary"]

    def test_cpu_underutilization_not_triggered_when_well_utilized(self, default_config: RecommendationConfig) -> None:
        """Container consuming 45% of request (> 25% threshold) does not trigger recommendation."""
        spec = WorkloadResourceSpec(
            container_name="web",
            cpu_request_str="500m",
            cpu_request_millicores=500,
        )
        stats = MetricStatistics(
            sample_count=100,
            duration_hours=24.0,
            avg_value=0.18,
            p95_value=0.225,  # 225m = 45% of 500m
            peak_value=0.30,
            is_sufficient=True,
        )

        rec = evaluate_cpu_underutilization(
            cluster_id="prod-1",
            namespace="default",
            workload_type="Deployment",
            workload_name="web-service",
            spec=spec,
            cpu_stats=stats,
            config=default_config,
        )

        assert rec is None

    def test_cpu_underutilization_skipped_without_request(self, default_config: RecommendationConfig) -> None:
        """Containers without configured CPU requests are safely ignored."""
        spec = WorkloadResourceSpec(container_name="batch")
        stats = MetricStatistics(
            sample_count=100,
            duration_hours=24.0,
            p95_value=0.05,
            is_sufficient=True,
        )
        rec = evaluate_cpu_underutilization(
            cluster_id="prod-1",
            namespace="default",
            workload_type="Deployment",
            workload_name="batch-worker",
            spec=spec,
            cpu_stats=stats,
            config=default_config,
        )
        assert rec is None

    def test_memory_underutilization_triggered(self, default_config: RecommendationConfig) -> None:
        """Container with 1Gi request peaking at 200Mi (19.5% < 30%) triggers memory right-sizing."""
        spec = WorkloadResourceSpec(
            container_name="api",
            memory_request_str="1Gi",
            memory_request_bytes=1024 * 1024 * 1024,  # 1024 MiB
        )
        stats = MetricStatistics(
            sample_count=100,
            duration_hours=24.0,
            avg_value=150 * 1024 * 1024,
            peak_value=200 * 1024 * 1024,  # 200 MiB
            is_sufficient=True,
        )

        rec = evaluate_memory_underutilization(
            cluster_id="prod-1",
            namespace="default",
            workload_type="Deployment",
            workload_name="api-gateway",
            spec=spec,
            mem_stats=stats,
            config=default_config,
        )

        assert rec is not None
        assert rec.recommendation_type == "memory_underutilization"
        # 200MiB * 1.25 headroom = 250MiB
        assert rec.current_configuration["recommended_spec"]["memory_request"] == "250Mi"
        assert rec.measured_usage["freed_memory_bytes"] > 0
        assert "allocatable node memory" in rec.measured_usage["resource_reduction_summary"]

    def test_high_memory_limit_risk_triggered(self, default_config: RecommendationConfig) -> None:
        """Container peaking at 900Mi of 1000Mi limit (90% >= 85%) triggers OOM prevention warning."""
        spec = WorkloadResourceSpec(
            container_name="db",
            memory_limit_str="1000Mi",
            memory_limit_bytes=1000 * 1024 * 1024,
        )
        stats = MetricStatistics(
            sample_count=50,
            duration_hours=12.0,
            peak_value=900 * 1024 * 1024,  # 900 MiB
            is_sufficient=True,
        )

        rec = evaluate_high_memory_limit_utilization(
            cluster_id="prod-1",
            namespace="database",
            workload_type="StatefulSet",
            workload_name="postgres",
            spec=spec,
            mem_stats=stats,
            config=default_config,
        )

        assert rec is not None
        assert rec.recommendation_type == "high_memory_limit_utilization"
        # 900MiB * 1.25 headroom = 1125MiB
        assert rec.current_configuration["recommended_spec"]["memory_limit"] == "1125Mi"
        assert "OOM termination boundary" in rec.recommendation_text

    def test_insufficient_historical_data_advisory(self, default_config: RecommendationConfig) -> None:
        """Workload with requests configured but insufficient metrics gets an explicit advisory notice."""
        spec = WorkloadResourceSpec(
            container_name="worker",
            cpu_request_str="500m",
            cpu_request_millicores=500,
        )
        stats = MetricStatistics(
            sample_count=4,
            duration_hours=1.5,
            is_sufficient=False,
            insufficiency_reason="Observation window (1.5h) is shorter than required minimum (6.0h).",
        )

        rec = evaluate_insufficient_historical_data(
            cluster_id="prod-1",
            namespace="jobs",
            workload_type="Deployment",
            workload_name="queue-consumer",
            spec=spec,
            stats=stats,
            metric_name="CPU",
            config=default_config,
        )

        assert rec is not None
        assert rec.recommendation_type == "insufficient_historical_data"
        assert rec.measured_usage["metric_name"] == "CPU"
        assert "Observation window (1.5h) is shorter" in rec.recommendation_text
        assert "observation_in_progress" in rec.current_configuration["spec"]["status"]


# ---------------------------------------------------------------------------
# 3. Workload Aggregation & Engine Tests
# ---------------------------------------------------------------------------

class TestRecommendationEngine:
    """Validate full evaluation across workloads, metrics mapping, and persistence."""

    def test_evaluate_workloads_from_data(self, default_config: RecommendationConfig) -> None:
        """Simulate deployments with pods and Prometheus series."""
        engine = RecommendationEngine(settings=None, config=default_config)  # type: ignore

        deployments = [
            DeploymentInfo(
                name="frontend",
                namespace="default",
                replicas=2,
                available_replicas=2,
            )
        ]
        pods = [
            PodInfo(
                name="frontend-abc-1",
                namespace="default",
                phase="Running",
                containers=[
                    ContainerInfo(
                        name="web",
                        image="nginx:alpine",
                        ready=True,
                        resources=ContainerResources(
                            cpu_request="1000m",
                            memory_request="512Mi",
                            memory_limit="1Gi",
                        ),
                    )
                ],
            ),
            PodInfo(
                name="frontend-abc-2",
                namespace="default",
                phase="Running",
                containers=[
                    ContainerInfo(
                        name="web",
                        image="nginx:alpine",
                        ready=True,
                        resources=ContainerResources(
                            cpu_request="1000m",
                            memory_request="512Mi",
                            memory_limit="1Gi",
                        ),
                    )
                ],
            ),
        ]

        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=24)

        # 200 samples of 0.05 CPU (50m = 5% of 1000m request -> underutilized, 69% completeness over 24h)
        cpu_series = MetricSeries(
            metric_labels={"namespace": "default", "pod": "frontend-abc-1", "container": "web"},
            values=[MetricDataPoint(timestamp=1000.0 + i * 300, value=0.05) for i in range(200)],
        )
        mem_series = MetricSeries(
            metric_labels={"namespace": "default", "pod": "frontend-abc-1", "container": "web"},
            values=[MetricDataPoint(timestamp=1000.0 + i * 300, value=50 * 1024 * 1024) for i in range(200)],
        )

        candidates = engine.evaluate_workloads_from_data(
            deployments=deployments,
            pods=pods,
            cpu_metrics=MetricsResult(query_name="container_cpu_usage_cores", series=[cpu_series]),
            mem_metrics=MetricsResult(query_name="container_memory_usage_bytes", series=[mem_series]),
            start_time=start,
            end_time=now,
            cluster_id="test-cluster",
        )

        assert len(candidates) >= 2  # CPU underutilization + memory underutilization
        types = {c.recommendation_type for c in candidates}
        assert "cpu_underutilization" in types
        assert "memory_underutilization" in types

    def test_persistence_and_review_lifecycle(self, db_session: Session) -> None:
        """Verify insertion, deduplication on repeat evaluation, and review status preservation."""
        engine = RecommendationEngine(settings=None)  # type: ignore

        cand = RecommendationCandidate(
            cluster_id="test-cluster",
            namespace="default",
            workload_type="Deployment",
            workload_name="auth-service",
            container_name="auth",
            recommendation_type="cpu_underutilization",
            observation_window="24h",
            current_configuration={"cpu_request": "1000m"},
            measured_usage={"p95_cpu_millicores": 80},
            recommendation_text="Initial recommendation",
        )

        # 1. First run creates the record
        res1 = engine.persist_recommendations(db_session, [cand])
        assert res1["created"] == 1
        assert res1["updated"] == 0

        rec = db_session.get(ResourceRecommendation, cand.fingerprint)
        assert rec is not None
        assert rec.review_status == "pending"

        # 2. Second run with updated telemetry updates the existing pending record
        cand.recommendation_text = "Updated recommendation narrative"
        res2 = engine.persist_recommendations(db_session, [cand])
        assert res2["created"] == 0
        assert res2["updated"] == 1

        db_session.refresh(rec)
        assert rec.recommendation_text == "Updated recommendation narrative"

        # 3. User reviews and marks as applied
        rec.review_status = "applied"
        db_session.commit()

        # 4. Third run does not overwrite user's applied status
        res3 = engine.persist_recommendations(db_session, [cand])
        assert res3["created"] == 0
        assert res3["updated"] == 0
        assert res3["unchanged"] == 1

        db_session.refresh(rec)
        assert rec.review_status == "applied"


# ---------------------------------------------------------------------------
# 4. API Endpoints Tests
# ---------------------------------------------------------------------------

class TestRecommendationApi:
    """Validate REST endpoints under /api/recommendations."""

    def test_list_and_filter_recommendations(self, api_client: TestClient, db_session: Session) -> None:
        """Create records in DB and verify listing and filtering."""
        r1 = ResourceRecommendation(
            id=str(uuid.uuid4()),
            cluster_id="default",
            namespace="prod",
            workload_type="Deployment",
            workload_name="web",
            recommendation_type="cpu_underutilization",
            observation_window="24h",
            current_configuration={"spec": {"cpu_request": "1000m"}, "recommended_spec": {"cpu_request": "150m"}},
            measured_usage={"resource_reduction_summary": "Frees 850m CPU"},
            recommendation_text="Reduce CPU requests.",
            review_status="pending",
        )
        r2 = ResourceRecommendation(
            id=str(uuid.uuid4()),
            cluster_id="default",
            namespace="staging",
            workload_type="Deployment",
            workload_name="worker",
            recommendation_type="memory_underutilization",
            observation_window="24h",
            current_configuration={"spec": {"memory_request": "2Gi"}, "recommended_spec": {"memory_request": "512Mi"}},
            measured_usage={"resource_reduction_summary": "Frees 1.5Gi Memory"},
            recommendation_text="Reduce memory requests.",
            review_status="applied",
        )
        db_session.add_all([r1, r2])
        db_session.commit()

        # List all
        resp = api_client.get("/api/recommendations")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data) == 2

        # Verify computed fields match frontend expectations
        item = next(x for x in data if x["id"] == r1.id)
        assert item["status"] == "open"  # pending mapped to open
        assert item["workload_name"] == "web"
        assert item["resource_type"] == "Deployment"
        assert item["current_spec"] == {"cpu_request": "1000m"}
        assert item["recommended_spec"] == {"cpu_request": "150m"}
        assert item["estimated_savings"] == "Frees 850m CPU"

        # Filter by namespace
        resp_filtered = api_client.get("/api/recommendations?namespace=prod")
        assert resp_filtered.status_code == 200
        filtered_data = resp_filtered.json()["data"]
        assert len(filtered_data) == 1
        assert filtered_data[0]["namespace"] == "prod"

        # Filter by status 'applied'
        resp_status = api_client.get("/api/recommendations?status=applied")
        assert resp_status.status_code == 200
        status_data = resp_status.json()["data"]
        assert len(status_data) == 1
        assert status_data[0]["id"] == r2.id

    def test_get_recommendation_by_id(self, api_client: TestClient, db_session: Session) -> None:
        rec_id = str(uuid.uuid4())
        rec = ResourceRecommendation(
            id=rec_id,
            cluster_id="default",
            namespace="prod",
            workload_type="Deployment",
            workload_name="cache",
            recommendation_type="high_memory_limit_utilization",
            observation_window="24h",
            current_configuration={"spec": {"memory_limit": "512Mi"}},
            measured_usage={},
            recommendation_text="Memory limit near capacity.",
            review_status="pending",
        )
        db_session.add(rec)
        db_session.commit()

        resp = api_client.get(f"/api/recommendations/{rec_id}")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == rec_id
        assert data["recommendation_type"] == "high_memory_limit_utilization"

        # Non-existent ID returns 404
        resp404 = api_client.get("/api/recommendations/non-existent-id")
        assert resp404.status_code == 404

    def test_update_recommendation_status(self, api_client: TestClient, db_session: Session) -> None:
        rec_id = str(uuid.uuid4())
        rec = ResourceRecommendation(
            id=rec_id,
            cluster_id="default",
            namespace="prod",
            workload_type="Deployment",
            workload_name="api",
            recommendation_type="cpu_underutilization",
            observation_window="24h",
            current_configuration={},
            measured_usage={},
            recommendation_text="Sizing recommendation",
            review_status="pending",
        )
        db_session.add(rec)
        db_session.commit()

        # Update to applied via PATCH
        resp = api_client.patch(f"/api/recommendations/{rec_id}", json={"review_status": "applied"})
        assert resp.status_code == 200
        assert resp.json()["data"]["review_status"] == "applied"
        assert resp.json()["data"]["status"] == "applied"

        # Update to dismissed via POST /status alias
        resp_post = api_client.post(f"/api/recommendations/{rec_id}/status", json={"review_status": "dismissed"})
        assert resp_post.status_code == 200
        assert resp_post.json()["data"]["review_status"] == "dismissed"

        # Invalid status returns 400
        bad_resp = api_client.patch(f"/api/recommendations/{rec_id}", json={"review_status": "invalid_choice"})
        assert bad_resp.status_code == 400

    def test_trigger_evaluation_endpoint(self, api_client: TestClient) -> None:
        """Trigger on-demand evaluation route returns execution summary."""
        resp = api_client.post("/api/recommendations/evaluate")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "created" in data
        assert "updated" in data
        assert "total_candidates" in data
