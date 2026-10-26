"""Prometheus service — curated, read-only metric queries.

This module uses HTTPX to call the Prometheus HTTP API.
All PromQL is defined internally — **no arbitrary user-supplied
PromQL is ever forwarded to Prometheus**.

Metric names
------------
The queries below rely on metrics exposed by **kube-state-metrics**
and **node-exporter** as deployed in a standard kube-prometheus-stack
installation.  The exact metric names MUST be verified against the
local Prometheus instance before each query is considered production-
ready.  Unverified metrics are clearly marked.

Verified metrics (standard kube-prometheus-stack defaults):
  * ``node_cpu_seconds_total``          – node-exporter
  * ``node_memory_MemTotal_bytes``      – node-exporter
  * ``node_memory_MemAvailable_bytes``  – node-exporter
  * ``container_cpu_usage_seconds_total`` – cAdvisor / kubelet
  * ``container_memory_working_set_bytes`` – cAdvisor / kubelet

These metric names are widely standard, but always confirm with:
  ``curl http://localhost:9090/api/v1/label/__name__/values``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import Settings
from app.schemas.models import MetricDataPoint, MetricSeries, MetricsResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PrometheusConnectionError(Exception):
    """Raised when Prometheus is unreachable."""


class PrometheusQueryError(Exception):
    """Raised when Prometheus returns a non-success response."""


# ---------------------------------------------------------------------------
# Curated queries
# ---------------------------------------------------------------------------

# Each entry maps a human-readable query name to a PromQL template.
# Templates may contain ``{placeholders}`` that are substituted at
# call time.  The placeholder values are always validated before
# substitution — they are NEVER raw user input injected into PromQL.

CURATED_QUERIES: Dict[str, str] = {
    # ----- Node-level metrics -----

    # Per-node CPU usage percentage (1 minus idle fraction).
    "node_cpu_usage_percent": (
        '100 - (avg by (instance) (rate(node_cpu_seconds_total{{mode="idle"}}[5m])) * 100)'
    ),

    # Per-node memory usage percentage.
    "node_memory_usage_percent": (
        "100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)"
    ),

    # ----- Pod / container-level metrics -----

    # Per-pod CPU usage in cores (summed across containers).
    "pod_cpu_usage_cores": (
        'sum by (namespace, pod) (rate(container_cpu_usage_seconds_total{{namespace=~"{namespace}", pod=~"{pod}", container!=""}}[5m]))'
    ),

    # Per-pod memory working set in bytes (summed across containers).
    "pod_memory_usage_bytes": (
        'sum by (namespace, pod) (container_memory_working_set_bytes{{namespace=~"{namespace}", pod=~"{pod}", container!=""}})'
    ),

    # ----- Cluster-wide utilisation (for overview) -----

    # Cluster-wide CPU usage percentage.
    "cluster_cpu_usage_percent": (
        '100 - (avg(rate(node_cpu_seconds_total{{mode="idle"}}[5m])) * 100)'
    ),

    # Cluster-wide memory usage percentage.
    "cluster_memory_usage_percent": (
        "100 * (1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes))"
    ),
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class PrometheusService:
    """Async client for curated Prometheus queries."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.prometheus_url.rstrip("/")
        self._timeout = settings.prometheus_timeout_seconds
        self._client: Optional[httpx.AsyncClient] = None

    # -- lifecycle -----------------------------------------------------------

    async def start(self) -> None:
        """Create the HTTPX async client."""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout,
        )

    async def close(self) -> None:
        """Close the HTTPX async client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # -- health --------------------------------------------------------------

    async def check_health(self) -> bool:
        """Return ``True`` if Prometheus is reachable."""
        try:
            client = self._ensure_client()
            response = await client.get("/-/healthy")
            return response.status_code == 200
        except Exception:
            return False

    # -- queries -------------------------------------------------------------

    async def instant_query(
        self,
        query_name: str,
        *,
        namespace: str = ".*",
        pod: str = ".*",
        node: str = ".*",
    ) -> MetricsResult:
        """Execute a curated instant query against Prometheus.

        ``query_name`` must be a key in ``CURATED_QUERIES``.
        Returns a ``MetricsResult``; on failure, ``error`` is set
        instead of ``series``.
        """
        template = CURATED_QUERIES.get(query_name)
        if template is None:
            return MetricsResult(
                query_name=query_name,
                error=f"Unknown query name: {query_name!r}",
            )

        promql = template.format(
            namespace=_sanitize_label(namespace),
            pod=_sanitize_label(pod),
            node=_sanitize_label(node),
        )

        return await self._execute_query(
            "/api/v1/query", {"query": promql}, query_name
        )

    async def range_query(
        self,
        query_name: str,
        start: datetime,
        end: datetime,
        step_seconds: int = 60,
        *,
        namespace: str = ".*",
        pod: str = ".*",
        node: str = ".*",
    ) -> MetricsResult:
        """Execute a curated range query against Prometheus.

        ``query_name`` must be a key in ``CURATED_QUERIES``.
        """
        template = CURATED_QUERIES.get(query_name)
        if template is None:
            return MetricsResult(
                query_name=query_name,
                error=f"Unknown query name: {query_name!r}",
            )

        promql = template.format(
            namespace=_sanitize_label(namespace),
            pod=_sanitize_label(pod),
            node=_sanitize_label(node),
        )

        params = {
            "query": promql,
            "start": start.timestamp(),
            "end": end.timestamp(),
            "step": f"{step_seconds}s",
        }

        return await self._execute_query(
            "/api/v1/query_range", params, query_name
        )

    async def get_cluster_cpu_percent(self) -> Optional[float]:
        """Return a single float for cluster-wide CPU usage, or None."""
        result = await self.instant_query("cluster_cpu_usage_percent")
        return _extract_scalar(result)

    async def get_cluster_memory_percent(self) -> Optional[float]:
        """Return a single float for cluster-wide memory usage, or None."""
        result = await self.instant_query("cluster_memory_usage_percent")
        return _extract_scalar(result)

    # -- internals -----------------------------------------------------------

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise PrometheusConnectionError(
                "Prometheus client is not started. Call start() first."
            )
        return self._client

    async def _execute_query(
        self,
        path: str,
        params: dict[str, Any],
        query_name: str,
    ) -> MetricsResult:
        """Execute a Prometheus HTTP API request and parse the result."""
        try:
            client = self._ensure_client()
            response = await client.get(path, params=params)

            if response.status_code != 200:
                return MetricsResult(
                    query_name=query_name,
                    error=(
                        f"Prometheus returned HTTP {response.status_code}: "
                        f"{response.text[:200]}"
                    ),
                )

            body = response.json()
            if body.get("status") != "success":
                return MetricsResult(
                    query_name=query_name,
                    error=f"Prometheus query failed: {body.get('error', 'unknown')}",
                )

            return _parse_prometheus_response(body, query_name)

        except httpx.ConnectError as exc:
            return MetricsResult(
                query_name=query_name,
                error=f"Prometheus unreachable: {exc}",
            )
        except httpx.TimeoutException:
            return MetricsResult(
                query_name=query_name,
                error="Prometheus query timed out",
            )
        except Exception as exc:
            logger.exception("Unexpected error querying Prometheus")
            return MetricsResult(
                query_name=query_name,
                error=f"Unexpected error: {exc}",
            )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_label(value: str) -> str:
    """Sanitize a label value for safe inclusion in PromQL.

    Allows only alphanumeric characters, hyphens, underscores, dots,
    and the regex wildcard ``.*``.  Everything else is stripped.
    """
    if value == ".*":
        return value
    return "".join(c for c in value if c.isalnum() or c in "-_.")


def _parse_prometheus_response(
    body: Dict[str, Any], query_name: str
) -> MetricsResult:
    """Parse Prometheus JSON into typed ``MetricsResult``."""
    data = body.get("data", {})
    result_type = data.get("resultType", "")
    results = data.get("result", [])

    series_list: List[MetricSeries] = []

    for item in results:
        labels = item.get("metric", {})
        points: List[MetricDataPoint] = []

        if result_type == "matrix":
            for ts, val in item.get("values", []):
                try:
                    points.append(
                        MetricDataPoint(timestamp=float(ts), value=float(val))
                    )
                except (ValueError, TypeError):
                    continue
        elif result_type == "vector":
            pair = item.get("value", [])
            if len(pair) == 2:
                try:
                    points.append(
                        MetricDataPoint(
                            timestamp=float(pair[0]), value=float(pair[1])
                        )
                    )
                except (ValueError, TypeError):
                    pass

        series_list.append(MetricSeries(metric_labels=labels, values=points))

    return MetricsResult(query_name=query_name, series=series_list)


def _extract_scalar(result: MetricsResult) -> Optional[float]:
    """Pull a single float from an instant query result, or ``None``."""
    if result.error or not result.series:
        return None
    first = result.series[0]
    if not first.values:
        return None
    return round(first.values[0].value, 2)
