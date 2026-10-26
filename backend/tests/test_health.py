"""Tests for the health endpoint (/api/health)."""

from __future__ import annotations


class TestHealthEndpoint:
    """Verify /api/health responses."""

    def test_health_all_ok(self, test_client) -> None:
        """When all components are healthy, status is 'ok'."""
        response = test_client.get("/api/health")
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "ok"
        assert body["data"]["healthy"] is True
        assert len(body["data"]["components"]) == 2

    def test_health_kubernetes_down(self, test_client, mock_k8s_service) -> None:
        """When Kubernetes is unreachable, report degraded."""
        mock_k8s_service.check_health.return_value = False

        response = test_client.get("/api/health")
        body = response.json()

        assert body["status"] == "degraded"
        assert body["data"]["healthy"] is False

        k8s_comp = next(
            c for c in body["data"]["components"] if c["name"] == "kubernetes"
        )
        assert k8s_comp["healthy"] is False

    def test_health_prometheus_down(self, test_client, mock_prom_service) -> None:
        """When Prometheus is unreachable, report degraded."""
        mock_prom_service.check_health.return_value = False

        response = test_client.get("/api/health")
        body = response.json()

        assert body["status"] == "degraded"

        prom_comp = next(
            c for c in body["data"]["components"] if c["name"] == "prometheus"
        )
        assert prom_comp["healthy"] is False

    def test_health_response_has_timestamp(self, test_client) -> None:
        """Every response should include a timestamp."""
        response = test_client.get("/api/health")
        body = response.json()
        assert "timestamp" in body
