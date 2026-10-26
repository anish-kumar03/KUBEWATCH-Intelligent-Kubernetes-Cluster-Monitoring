"""Cluster overview endpoint.

Aggregates node count, pod count, namespace count, deployment count,
and cluster-wide CPU/memory utilisation.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.schemas.models import ApiResponse, ClusterOverview
from app.services.kubernetes_service import (
    KubernetesApiError,
    KubernetesConnectionError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/cluster/overview",
    response_model=ApiResponse[ClusterOverview],
    summary="Cluster overview",
    description="Aggregated cluster-level summary including utilisation.",
)
async def cluster_overview(request: Request) -> ApiResponse[ClusterOverview]:
    """Build a cluster overview from K8s + Prometheus data."""
    k8s_service = request.app.state.kubernetes_service
    prom_service = request.app.state.prometheus_service

    try:
        overview = k8s_service.get_cluster_overview()
    except (KubernetesConnectionError, KubernetesApiError) as exc:
        logger.error("Kubernetes unavailable for cluster overview: %s", exc)
        return ApiResponse(
            status="error",
            error=f"Kubernetes API unavailable: {exc}",
        )

    # Enrich with Prometheus utilisation (nullable on failure)
    try:
        overview.cpu_usage_percent = (
            await prom_service.get_cluster_cpu_percent()
        )
        overview.memory_usage_percent = (
            await prom_service.get_cluster_memory_percent()
        )
    except Exception as exc:
        logger.warning(
            "Prometheus unavailable for cluster utilisation: %s", exc
        )
        # Leave as None — never fake a zero value

    return ApiResponse(status="ok", data=overview)
