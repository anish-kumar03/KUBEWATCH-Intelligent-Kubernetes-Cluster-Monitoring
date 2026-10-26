"""Metrics endpoints.

Serves curated CPU and memory metrics from Prometheus.
Supports both instant and range queries with validated parameters.

No arbitrary PromQL is exposed — only predefined query names from
``CURATED_QUERIES`` are accepted.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Query, Request

from app.schemas.models import ApiResponse, MetricsResult

logger = logging.getLogger(__name__)

router = APIRouter()

_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")

# Pod/node name: alphanumeric, hyphens, dots.
_RESOURCE_NAME_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9\-\.]{0,252}[a-z0-9])?$")


def _validate_time_range(
    start: Optional[datetime],
    end: Optional[datetime],
    max_hours: int,
) -> Optional[str]:
    """Validate the requested time range.

    Returns an error message or ``None`` if valid.
    """
    if start is not None and end is not None:
        if start >= end:
            return "start must be before end"
        delta = end - start
        if delta > timedelta(hours=max_hours):
            return (
                f"Time range exceeds maximum of {max_hours} hours "
                f"({max_hours // 24} days)"
            )
    return None


# ---------------------------------------------------------------------------
# CPU metrics
# ---------------------------------------------------------------------------


@router.get(
    "/metrics/cpu/nodes",
    response_model=ApiResponse[MetricsResult],
    summary="Node CPU usage",
    description="Per-node CPU usage percentage from Prometheus.",
)
async def node_cpu_metrics(
    request: Request,
    start: Optional[datetime] = Query(default=None, description="Range start (ISO 8601)"),
    end: Optional[datetime] = Query(default=None, description="Range end (ISO 8601)"),
    step: Optional[int] = Query(
        default=None, ge=10, le=3600, description="Step in seconds (10–3600)"
    ),
) -> ApiResponse[MetricsResult]:
    """Node-level CPU usage (instant or range)."""
    settings = request.app.state.settings
    prom_service = request.app.state.prometheus_service

    err = _validate_time_range(start, end, settings.max_query_range_hours)
    if err:
        return ApiResponse(status="error", error=err)

    if start and end:
        result = await prom_service.range_query(
            "node_cpu_usage_percent",
            start=start,
            end=end,
            step_seconds=step or settings.metrics_step_seconds,
        )
    else:
        result = await prom_service.instant_query("node_cpu_usage_percent")

    return ApiResponse(status="ok", data=result)


@router.get(
    "/metrics/cpu/pods",
    response_model=ApiResponse[MetricsResult],
    summary="Pod CPU usage",
    description="Per-pod CPU usage in cores from Prometheus.",
)
async def pod_cpu_metrics(
    request: Request,
    namespace: Optional[str] = Query(default=None, max_length=63),
    pod: Optional[str] = Query(default=None, max_length=253),
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    step: Optional[int] = Query(default=None, ge=10, le=3600),
) -> ApiResponse[MetricsResult]:
    """Pod-level CPU usage (instant or range)."""
    settings = request.app.state.settings
    prom_service = request.app.state.prometheus_service

    # Validate namespace
    if namespace and not _NAMESPACE_PATTERN.match(namespace):
        return ApiResponse(status="error", error=f"Invalid namespace: {namespace!r}")

    # Validate pod name
    if pod and not _RESOURCE_NAME_PATTERN.match(pod):
        return ApiResponse(status="error", error=f"Invalid pod name: {pod!r}")

    err = _validate_time_range(start, end, settings.max_query_range_hours)
    if err:
        return ApiResponse(status="error", error=err)

    kwargs = {
        "namespace": namespace or ".*",
        "pod": pod or ".*",
    }

    if start and end:
        result = await prom_service.range_query(
            "pod_cpu_usage_cores",
            start=start,
            end=end,
            step_seconds=step or settings.metrics_step_seconds,
            **kwargs,
        )
    else:
        result = await prom_service.instant_query("pod_cpu_usage_cores", **kwargs)

    return ApiResponse(status="ok", data=result)


# ---------------------------------------------------------------------------
# Memory metrics
# ---------------------------------------------------------------------------


@router.get(
    "/metrics/memory/nodes",
    response_model=ApiResponse[MetricsResult],
    summary="Node memory usage",
    description="Per-node memory usage percentage from Prometheus.",
)
async def node_memory_metrics(
    request: Request,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    step: Optional[int] = Query(default=None, ge=10, le=3600),
) -> ApiResponse[MetricsResult]:
    """Node-level memory usage (instant or range)."""
    settings = request.app.state.settings
    prom_service = request.app.state.prometheus_service

    err = _validate_time_range(start, end, settings.max_query_range_hours)
    if err:
        return ApiResponse(status="error", error=err)

    if start and end:
        result = await prom_service.range_query(
            "node_memory_usage_percent",
            start=start,
            end=end,
            step_seconds=step or settings.metrics_step_seconds,
        )
    else:
        result = await prom_service.instant_query("node_memory_usage_percent")

    return ApiResponse(status="ok", data=result)


@router.get(
    "/metrics/memory/pods",
    response_model=ApiResponse[MetricsResult],
    summary="Pod memory usage",
    description="Per-pod memory working set in bytes from Prometheus.",
)
async def pod_memory_metrics(
    request: Request,
    namespace: Optional[str] = Query(default=None, max_length=63),
    pod: Optional[str] = Query(default=None, max_length=253),
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    step: Optional[int] = Query(default=None, ge=10, le=3600),
) -> ApiResponse[MetricsResult]:
    """Pod-level memory usage (instant or range)."""
    settings = request.app.state.settings
    prom_service = request.app.state.prometheus_service

    if namespace and not _NAMESPACE_PATTERN.match(namespace):
        return ApiResponse(status="error", error=f"Invalid namespace: {namespace!r}")

    if pod and not _RESOURCE_NAME_PATTERN.match(pod):
        return ApiResponse(status="error", error=f"Invalid pod name: {pod!r}")

    err = _validate_time_range(start, end, settings.max_query_range_hours)
    if err:
        return ApiResponse(status="error", error=err)

    kwargs = {
        "namespace": namespace or ".*",
        "pod": pod or ".*",
    }

    if start and end:
        result = await prom_service.range_query(
            "pod_memory_usage_bytes",
            start=start,
            end=end,
            step_seconds=step or settings.metrics_step_seconds,
            **kwargs,
        )
    else:
        result = await prom_service.instant_query("pod_memory_usage_bytes", **kwargs)

    return ApiResponse(status="ok", data=result)
