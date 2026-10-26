"""Unit tests for KubernetesService (app.services.kubernetes_service)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from kubernetes.client.rest import ApiException

from app.core.config import KubernetesMode, Settings
from app.services.kubernetes_service import (
    KubernetesApiError,
    KubernetesConnectionError,
    KubernetesService,
    _parse_cpu,
    _parse_memory,
)


class TestQuantityParsers:
    """Verify CPU and memory string parsing."""

    def test_parse_cpu_millicores(self) -> None:
        assert _parse_cpu("500m") == 500
        assert _parse_cpu("100m") == 100

    def test_parse_cpu_cores(self) -> None:
        assert _parse_cpu("2") == 2000
        assert _parse_cpu("0.5") == 500

    def test_parse_cpu_invalid_or_none(self) -> None:
        assert _parse_cpu(None) == 0
        assert _parse_cpu("") == 0
        assert _parse_cpu("not-a-number") == 0

    def test_parse_memory_binary_si(self) -> None:
        assert _parse_memory("1024Ki") == 1024 * 1024
        assert _parse_memory("128Mi") == 128 * 1024 * 1024
        assert _parse_memory("4Gi") == 4 * 1024 * 1024 * 1024

    def test_parse_memory_decimal_si(self) -> None:
        assert _parse_memory("1000K") == 1000 * 1000
        assert _parse_memory("500M") == 500 * 1000 * 1000
        assert _parse_memory("2G") == 2 * 1000 * 1000 * 1000

    def test_parse_memory_plain_integer(self) -> None:
        assert _parse_memory("1048576") == 1048576

    def test_parse_memory_invalid_or_none(self) -> None:
        assert _parse_memory(None) == 0
        assert _parse_memory("") == 0
        assert _parse_memory("invalid") == 0


class TestKubernetesServiceConnection:
    """Verify connection behavior and failure handling."""

    def test_connect_local_mode(self) -> None:
        settings = Settings(kubernetes_mode=KubernetesMode.LOCAL, kube_context="dev-cluster")
        service = KubernetesService(settings)

        with patch("kubernetes.config.load_kube_config") as mock_load:
            service.connect()
            mock_load.assert_called_once_with(context="dev-cluster")
            assert service._core_v1 is not None
            assert service._apps_v1 is not None

    def test_connect_in_cluster_mode(self) -> None:
        settings = Settings(kubernetes_mode=KubernetesMode.IN_CLUSTER)
        service = KubernetesService(settings)

        with patch("kubernetes.config.load_incluster_config") as mock_load:
            service.connect()
            mock_load.assert_called_once()
            assert service._core_v1 is not None
            assert service._apps_v1 is not None

    def test_connect_failure_raises_kubernetes_connection_error(self) -> None:
        settings = Settings(kubernetes_mode=KubernetesMode.LOCAL)
        service = KubernetesService(settings)

        with patch("kubernetes.config.load_kube_config", side_effect=RuntimeError("Kubeconfig missing")):
            with pytest.raises(KubernetesConnectionError) as exc_info:
                service.connect()
            assert "Failed to initialise" in str(exc_info.value)

    def test_unconnected_calls_raise_error(self) -> None:
        settings = Settings()
        service = KubernetesService(settings)

        with pytest.raises(KubernetesConnectionError) as exc_info:
            service.list_nodes()
        assert "not connected" in str(exc_info.value).lower()


class TestKubernetesServiceOperations:
    """Verify operations with mocked client APIs."""

    @pytest.fixture
    def connected_service(self) -> KubernetesService:
        settings = Settings()
        service = KubernetesService(settings)
        service._core_v1 = MagicMock()
        service._apps_v1 = MagicMock()
        return service

    def test_check_health_true(self, connected_service: KubernetesService) -> None:
        connected_service._core_v1.get_api_resources.return_value = MagicMock()
        assert connected_service.check_health() is True

    def test_check_health_false_on_exception(self, connected_service: KubernetesService) -> None:
        connected_service._core_v1.get_api_resources.side_effect = RuntimeError("API error")
        assert connected_service.check_health() is False

    def test_list_namespaces_success(self, connected_service: KubernetesService) -> None:
        ns1 = MagicMock()
        ns1.metadata.name = "default"
        ns2 = MagicMock()
        ns2.metadata.name = "kube-system"
        connected_service._core_v1.list_namespace.return_value = MagicMock(items=[ns1, ns2])

        result = connected_service.list_namespaces()
        assert result == ["default", "kube-system"]

    def test_list_namespaces_api_exception(self, connected_service: KubernetesService) -> None:
        connected_service._core_v1.list_namespace.side_effect = ApiException(status=500, reason="Server Error")
        with pytest.raises(KubernetesApiError) as exc_info:
            connected_service.list_namespaces()
        assert "Server Error" in str(exc_info.value)
