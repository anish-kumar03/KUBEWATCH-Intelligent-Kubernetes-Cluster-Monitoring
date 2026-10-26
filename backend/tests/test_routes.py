"""Tests for cluster, nodes, pods, and deployments endpoints."""

from __future__ import annotations

from app.schemas.models import (
    ClusterOverview,
    DeploymentInfo,
    NodeInfo,
    NodeResources,
    PodInfo,
)
from app.services.kubernetes_service import (
    KubernetesApiError,
    KubernetesConnectionError,
)


# ---------------------------------------------------------------------------
# Cluster overview
# ---------------------------------------------------------------------------


class TestClusterOverview:
    """Verify /api/cluster/overview responses."""

    def test_overview_ok(self, test_client, mock_k8s_service) -> None:
        """Returns an overview when K8s is available."""
        mock_k8s_service.get_cluster_overview.return_value = ClusterOverview(
            node_count=3,
            pod_count=25,
            namespace_count=4,
            deployment_count=5,
            cpu_capacity="12000m",
            memory_capacity="25769803776",
        )

        response = test_client.get("/api/cluster/overview")
        assert response.status_code == 200

        body = response.json()
        assert body["status"] == "ok"
        assert body["data"]["node_count"] == 3
        assert body["data"]["pod_count"] == 25

    def test_overview_k8s_error(self, test_client, mock_k8s_service) -> None:
        """Returns an error when K8s is unavailable."""
        mock_k8s_service.get_cluster_overview.side_effect = (
            KubernetesConnectionError("unreachable")
        )

        response = test_client.get("/api/cluster/overview")
        body = response.json()
        assert body["status"] == "error"
        assert "unavailable" in body["error"].lower()

    def test_overview_prometheus_unavailable(
        self, test_client, mock_k8s_service, mock_prom_service
    ) -> None:
        """CPU/memory should be None when Prometheus is down."""
        mock_k8s_service.get_cluster_overview.return_value = ClusterOverview(
            node_count=1,
            pod_count=5,
            namespace_count=2,
            deployment_count=1,
        )
        mock_prom_service.get_cluster_cpu_percent.return_value = None
        mock_prom_service.get_cluster_memory_percent.return_value = None

        response = test_client.get("/api/cluster/overview")
        body = response.json()
        assert body["status"] == "ok"
        assert body["data"]["cpu_usage_percent"] is None
        assert body["data"]["memory_usage_percent"] is None


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


class TestNodes:
    """Verify /api/nodes responses."""

    def test_nodes_ok(self, test_client, mock_k8s_service) -> None:
        """Returns nodes when available."""
        mock_k8s_service.list_nodes.return_value = [
            NodeInfo(
                name="node-1",
                status="Ready",
                capacity=NodeResources(cpu="4", memory="8Gi"),
                allocatable=NodeResources(cpu="3800m", memory="7Gi"),
            )
        ]

        response = test_client.get("/api/nodes")
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["data"]) == 1
        assert body["data"][0]["name"] == "node-1"

    def test_nodes_k8s_error(self, test_client, mock_k8s_service) -> None:
        """Returns error when K8s is unavailable."""
        mock_k8s_service.list_nodes.side_effect = KubernetesApiError("timeout")

        response = test_client.get("/api/nodes")
        body = response.json()
        assert body["status"] == "error"


# ---------------------------------------------------------------------------
# Pods
# ---------------------------------------------------------------------------


class TestPods:
    """Verify /api/pods responses."""

    def test_pods_ok(self, test_client, mock_k8s_service) -> None:
        """Returns pods when available."""
        mock_k8s_service.list_pods.return_value = [
            PodInfo(name="pod-1", namespace="default", phase="Running"),
        ]

        response = test_client.get("/api/pods")
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["data"]) == 1

    def test_pods_with_namespace(self, test_client, mock_k8s_service) -> None:
        """Namespace filter should be passed to the service."""
        mock_k8s_service.list_pods.return_value = []

        response = test_client.get("/api/pods?namespace=kube-system")
        assert response.status_code == 200
        mock_k8s_service.list_pods.assert_called_with(namespace="kube-system")

    def test_pods_invalid_namespace(self, test_client) -> None:
        """Invalid namespace should return an error, not call K8s."""
        response = test_client.get("/api/pods?namespace=INVALID!")
        body = response.json()
        assert body["status"] == "error"
        assert "invalid namespace" in body["error"].lower()

    def test_pods_k8s_error(self, test_client, mock_k8s_service) -> None:
        """Returns error when K8s is unavailable."""
        mock_k8s_service.list_pods.side_effect = KubernetesConnectionError(
            "not connected"
        )

        response = test_client.get("/api/pods")
        body = response.json()
        assert body["status"] == "error"


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------


class TestDeployments:
    """Verify /api/deployments responses."""

    def test_deployments_ok(self, test_client, mock_k8s_service) -> None:
        """Returns deployments when available."""
        mock_k8s_service.list_deployments.return_value = [
            DeploymentInfo(
                name="web",
                namespace="default",
                replicas=3,
                ready_replicas=3,
                available_replicas=3,
                unavailable_replicas=0,
            ),
        ]

        response = test_client.get("/api/deployments")
        body = response.json()
        assert body["status"] == "ok"
        assert len(body["data"]) == 1
        assert body["data"][0]["unavailable_replicas"] == 0

    def test_deployments_invalid_namespace(self, test_client) -> None:
        """Invalid namespace should return an error."""
        response = test_client.get("/api/deployments?namespace=BAD!")
        body = response.json()
        assert body["status"] == "error"
