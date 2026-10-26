"""Unit tests for PrometheusService (app.services.prometheus_service)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.config import Settings
from app.schemas.models import MetricDataPoint, MetricSeries, MetricsResult
from app.services.prometheus_service import (
    PrometheusConnectionError,
    PrometheusService,
    _extract_scalar,
    _parse_prometheus_response,
    _sanitize_label,
)


class TestPrometheusHelpers:
    """Verify Prometheus utility functions."""

    def test_sanitize_label_valid(self) -> None:
        assert _sanitize_label("kube-system") == "kube-system"
        assert _sanitize_label("app_1.2") == "app_1.2"
        assert _sanitize_label(".*") == ".*"

    def test_sanitize_label_strips_injection_chars(self) -> None:
        assert _sanitize_label('test", injection="val') == "testinjectionval"
        assert _sanitize_label("foo; rm -rf") == "foorm-rf"

    def test_extract_scalar_success(self) -> None:
        result = MetricsResult(
            query_name="test",
            series=[
                MetricSeries(
                    metric_labels={},
                    values=[MetricDataPoint(timestamp=1000.0, value=75.456)],
                )
            ],
        )
        assert _extract_scalar(result) == 75.46

    def test_extract_scalar_empty_or_error(self) -> None:
        assert _extract_scalar(MetricsResult(query_name="test", error="failed")) is None
        assert _extract_scalar(MetricsResult(query_name="test", series=[])) is None

    def test_parse_prometheus_response_vector(self) -> None:
        body = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"instance": "node-1"},
                        "value": [1600000000, "42.5"],
                    }
                ],
            },
        }
        res = _parse_prometheus_response(body, "test_vector")
        assert res.query_name == "test_vector"
        assert len(res.series) == 1
        assert res.series[0].metric_labels["instance"] == "node-1"
        assert res.series[0].values[0].value == 42.5

    def test_parse_prometheus_response_matrix(self) -> None:
        body = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"instance": "node-1"},
                        "values": [
                            [1600000000, "10.0"],
                            [1600000060, "20.0"],
                        ],
                    }
                ],
            },
        }
        res = _parse_prometheus_response(body, "test_matrix")
        assert len(res.series) == 1
        assert len(res.series[0].values) == 2
        assert res.series[0].values[1].value == 20.0


@pytest.mark.asyncio
class TestPrometheusServiceOperations:
    """Verify PrometheusService API calls with mocked HTTP transport."""

    async def test_ensure_client_not_started_raises_error(self) -> None:
        service = PrometheusService(Settings())
        with pytest.raises(PrometheusConnectionError):
            service._ensure_client()

    async def test_check_health_true(self) -> None:
        service = PrometheusService(Settings())
        service._client = AsyncMock(spec=httpx.AsyncClient)
        service._client.get.return_value = MagicMock(status_code=200)

        assert await service.check_health() is True

    async def test_check_health_false_on_status_or_exception(self) -> None:
        service = PrometheusService(Settings())
        service._client = AsyncMock(spec=httpx.AsyncClient)
        service._client.get.return_value = MagicMock(status_code=503)

        assert await service.check_health() is False

    async def test_instant_query_unknown_name(self) -> None:
        service = PrometheusService(Settings())
        service._client = AsyncMock(spec=httpx.AsyncClient)

        result = await service.instant_query("unknown_query_name")
        assert result.error is not None
        assert "Unknown query name" in result.error

    async def test_instant_query_connect_error(self) -> None:
        service = PrometheusService(Settings())
        service._client = AsyncMock(spec=httpx.AsyncClient)
        service._client.get.side_effect = httpx.ConnectError("Connection refused")

        result = await service.instant_query("node_cpu_usage_percent")
        assert result.error is not None
        assert "unreachable" in result.error.lower()

    async def test_instant_query_timeout(self) -> None:
        service = PrometheusService(Settings())
        service._client = AsyncMock(spec=httpx.AsyncClient)
        service._client.get.side_effect = httpx.TimeoutException("Timed out")

        result = await service.instant_query("node_cpu_usage_percent")
        assert result.error is not None
        assert "timed out" in result.error.lower()

    async def test_range_query_success(self) -> None:
        service = PrometheusService(Settings())
        service._client = AsyncMock(spec=httpx.AsyncClient)
        mock_response = MagicMock(status_code=200)
        mock_response.json.return_value = {
            "status": "success",
            "data": {
                "resultType": "matrix",
                "result": [
                    {
                        "metric": {"pod": "test-pod"},
                        "values": [[1700000000, "0.15"]],
                    }
                ],
            },
        }
        service._client.get.return_value = mock_response

        now = datetime.now(timezone.utc)
        result = await service.range_query(
            "pod_cpu_usage_cores",
            start=now,
            end=now,
            step_seconds=60,
            namespace="default",
            pod="test-pod",
        )
        assert result.error is None
        assert len(result.series) == 1
        assert result.series[0].values[0].value == 0.15
