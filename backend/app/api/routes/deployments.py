"""Deployments endpoint.

Lists deployments with namespace filtering and availability data.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Query, Request

from app.schemas.models import ApiResponse, DeploymentInfo
from app.services.kubernetes_service import (
    KubernetesApiError,
    KubernetesConnectionError,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")


@router.get(
    "/deployments",
    response_model=ApiResponse[List[DeploymentInfo]],
    summary="List deployments",
    description=(
        "Returns all deployments with desired, ready, available, "
        "and unavailable replica counts."
    ),
)
async def list_deployments(
    request: Request,
    namespace: Optional[str] = Query(
        default=None,
        description="Kubernetes namespace to filter by.",
        max_length=63,
    ),
) -> ApiResponse[List[DeploymentInfo]]:
    """List deployments with optional namespace filtering."""
    if namespace is not None and not _NAMESPACE_PATTERN.match(namespace):
        return ApiResponse(
            status="error",
            error=(
                f"Invalid namespace: {namespace!r}. Must match "
                f"Kubernetes naming rules."
            ),
        )

    k8s_service = request.app.state.kubernetes_service

    try:
        deployments = k8s_service.list_deployments(namespace=namespace)
    except (KubernetesConnectionError, KubernetesApiError) as exc:
        logger.error("Failed to list deployments: %s", exc)
        return ApiResponse(
            status="error",
            error=f"Kubernetes API unavailable: {exc}",
        )

    return ApiResponse(status="ok", data=deployments)
