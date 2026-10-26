"""Nodes endpoint.

Lists all cluster nodes with status, capacity, allocatable
resources, and conditions.
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Request

from app.schemas.models import ApiResponse, NodeInfo
from app.services.kubernetes_service import (
    KubernetesApiError,
    KubernetesConnectionError,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/nodes",
    response_model=ApiResponse[List[NodeInfo]],
    summary="List cluster nodes",
    description=(
        "Returns all nodes with status, capacity, allocatable "
        "resources, and conditions."
    ),
)
async def list_nodes(request: Request) -> ApiResponse[List[NodeInfo]]:
    """List all cluster nodes (read-only)."""
    k8s_service = request.app.state.kubernetes_service

    try:
        nodes = k8s_service.list_nodes()
    except (KubernetesConnectionError, KubernetesApiError) as exc:
        logger.error("Failed to list nodes: %s", exc)
        return ApiResponse(
            status="error",
            error=f"Kubernetes API unavailable: {exc}",
        )

    return ApiResponse(status="ok", data=nodes)
