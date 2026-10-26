"""Tests for metrics endpoints (/api/metrics/*)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.schemas.models import MetricDataPoint, MetricSeries, MetricsResult


class TestMetricsEndpoints:
    """Verify CPU and memory metrics endpoints."""

    def test_node_cpu_instant(self, test_client, mock_prom_service) -> None:
        """Instant node CPU usage query returns expected structure."""
        now_ts = datetime.now(timezone.utc).timestamp()
        mock_prom_service.instant_query.return_value = MetricsResult(
            query_name="node_cpu_usage_percent",
            series=[
                MetricSeries(
                    metric_labels={"instance": "minikube"},
                    values=[MetricDataPoint(timestamp=now_ts, value=35.5)],
                )
            ],
        )

        response = test_client.get("/api/metrics/cpu/nodes")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["data"]["query_name"] == "node_cpu_usage_percent"
        assert len(body["data"]["series"]) == 1
        assert body["data"]["series"][0]["values"][0]["value"] == 35.5
        assert body["data"]["series"][0]["metric_labels"]["instance"] == "minikube"

    def test_node_cpu_range(self, test_client, mock_prom_service) -> None:
        """Range query for node CPU passes start, end, and step."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(hours=1)
        mock_prom_service.range_query.return_value = MetricsResult(
            query_name="node_cpu_usage_percent",
            series=[],
        )

        response = test_client.get(
            "/api/metrics/cpu/nodes",
            params={"start": start.isoformat(), "end": now.isoformat(), "step": 30},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        mock_prom_service.range_query.assert_called_once()

    def test_pod_cpu_instant(self, test_client, mock_prom_service) -> None:
        """Instant pod CPU query filters by namespace and pod name."""
        mock_prom_service.instant_query.return_value = MetricsResult(
            query_name="pod_cpu_usage_cores",
            series=[],
        )

        response = test_client.get(
            "/api/metrics/cpu/pods",
            params={"namespace": "kube-system", "pod": "coredns-1"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        mock_prom_service.instant_query.assert_called_with(
            "pod_cpu_usage_cores",
            namespace="kube-system",
            pod="coredns-1",
        )

    def test_node_memory_instant(self, test_client, mock_prom_service) -> None:
        """Instant node memory query returns expected structure."""
        now_ts = datetime.now(timezone.utc).timestamp()
        mock_prom_service.instant_query.return_value = MetricsResult(
            query_name="node_memory_usage_percent",
            series=[
                MetricSeries(
                    metric_labels={"instance": "minikube"},
                    values=[MetricDataPoint(timestamp=now_ts, value=62.8)],
                )
            ],
        )

        response = test_client.get("/api/metrics/memory/nodes")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["data"]["series"][0]["values"][0]["value"] == 62.8

    def test_pod_memory_instant(self, test_client, mock_prom_service) -> None:
        """Instant pod memory query passes parameters."""
        mock_prom_service.instant_query.return_value = MetricsResult(
            query_name="pod_memory_usage_bytes",
            series=[],
        )

        response = test_client.get(
            "/api/metrics/memory/pods",
            params={"namespace": "default"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        mock_prom_service.instant_query.assert_called_with(
            "pod_memory_usage_bytes",
            namespace="default",
            pod=".*",
        )

    def test_invalid_time_range_start_after_end(self, test_client) -> None:
        """Start time after end time must return validation error."""
        now = datetime.now(timezone.utc)
        start = now
        end = now - timedelta(hours=1)

        response = test_client.get(
            "/api/metrics/cpu/nodes",
            params={"start": start.isoformat(), "end": end.isoformat()},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert "start must be before end" in body["error"]

    def test_invalid_time_range_exceeds_max(self, test_client) -> None:
        """Time range exceeding max_query_range_hours must return error."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=8)  # Default max is 7 days (168 hours)

        response = test_client.get(
            "/api/metrics/cpu/nodes",
            params={"start": start.isoformat(), "end": now.isoformat()},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert "exceeds maximum" in body["error"]

    def test_invalid_namespace_format(self, test_client) -> None:
        """Malformed namespace fails validation."""
        response = test_client.get(
            "/api/metrics/cpu/pods",
            params={"namespace": "-invalid-ns"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert "Invalid namespace" in body["error"]

    def test_invalid_pod_name_format(self, test_client) -> None:
        """Malformed pod name fails validation."""
        response = test_client.get(
            "/api/metrics/cpu/pods",
            params={"pod": "POD$NAME"},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "error"
        assert "Invalid pod name" in body["error"]
