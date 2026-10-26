"""Pytest fixtures shared across all backend tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.config import KubernetesMode, Settings
from app.services.kubernetes_service import KubernetesService
from app.services.prometheus_service import PrometheusService


@pytest.fixture
def settings() -> Settings:
    """Return a Settings instance for testing."""
    return Settings(
        kubernetes_mode=KubernetesMode.LOCAL,
        prometheus_url="http://localhost:9090",
        cors_origins=["http://localhost:5173"],
        log_level="DEBUG",
    )


@pytest.fixture
def mock_k8s_service(settings: Settings) -> MagicMock:
    """Return a mocked KubernetesService that is already 'connected'."""
    service = MagicMock(spec=KubernetesService)
    service.check_health.return_value = True
    service.list_nodes.return_value = []
    service.list_pods.return_value = []
    service.list_deployments.return_value = []
    service.list_namespaces.return_value = ["default", "kube-system"]
    return service


@pytest.fixture
def mock_prom_service() -> AsyncMock:
    """Return a mocked PrometheusService."""
    service = AsyncMock(spec=PrometheusService)
    service.check_health.return_value = True
    service.get_cluster_cpu_percent.return_value = 42.5
    service.get_cluster_memory_percent.return_value = 65.3
    return service


@pytest.fixture
def test_client(
    mock_k8s_service: MagicMock,
    mock_prom_service: AsyncMock,
    settings: Settings,
) -> TestClient:
    """Create a FastAPI TestClient with mocked services.

    This patches the Kubernetes config loading so tests don't require
    a live cluster.
    """
    with patch(
        "app.services.kubernetes_service.k8s_config.load_kube_config"
    ):
        from app.main import create_app

        app = create_app(lifespan_handler=None)

    # Override app state with mocks
    app.state.settings = settings
    app.state.kubernetes_service = mock_k8s_service
    app.state.prometheus_service = mock_prom_service

    # Use TestClient with lifespan disabled (we manage state manually)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
