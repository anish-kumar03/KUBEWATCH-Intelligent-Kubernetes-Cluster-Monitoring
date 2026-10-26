"""Pods endpoint.

Lists pods with namespace filtering and validation.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Query, Request

from app.schemas.models import ApiResponse, PodInfo
from app.services.kubernetes_service import (
    KubernetesApiError,
    KubernetesConnectionError,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Namespace must be a valid Kubernetes namespace name:
# lowercase alphanumeric + hyphens, max 63 chars.
_NAMESPACE_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")


@router.get(
    "/pods",
    response_model=ApiResponse[List[PodInfo]],
    summary="List pods",
    description=(
        "Returns all pods, optionally filtered by namespace. "
        "The namespace parameter is validated against Kubernetes "
        "naming rules."
    ),
)
async def list_pods(
    request: Request,
    namespace: Optional[str] = Query(
        default=None,
        description="Kubernetes namespace to filter by.",
        max_length=63,
    ),
) -> ApiResponse[List[PodInfo]]:
    """List pods with optional namespace filtering."""
    # Validate namespace format
    if namespace is not None and not _NAMESPACE_PATTERN.match(namespace):
        return ApiResponse(
            status="error",
            error=(
                f"Invalid namespace: {namespace!r}. Must match "
                f"Kubernetes naming rules (lowercase alphanumeric and hyphens, "
                f"max 63 characters)."
            ),
        )

    k8s_service = request.app.state.kubernetes_service

    try:
        pods = k8s_service.list_pods(namespace=namespace)
    except (KubernetesConnectionError, KubernetesApiError) as exc:
        logger.error("Failed to list pods: %s", exc)
        return ApiResponse(
            status="error",
            error=f"Kubernetes API unavailable: {exc}",
        )

    return ApiResponse(status="ok", data=pods)
