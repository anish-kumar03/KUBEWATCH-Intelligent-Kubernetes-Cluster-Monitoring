"""Resource recommendations endpoints — list, filter, retrieve details, review, and evaluate."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import get_db
from app.models.recommendation import ResourceRecommendation
from app.recommendations.calculator import utc_now
from app.recommendations.engine import RecommendationEngine
from app.schemas.models import ApiResponse
from app.schemas.persistence import (
    ResourceRecommendationRead,
    ResourceRecommendationUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/recommendations",
    response_model=ApiResponse[List[ResourceRecommendationRead]],
    summary="List and filter resource sizing recommendations",
    description=(
        "Returns advisory recommendations ordered by recency. "
        "Supports filtering by namespace, workload type, recommendation type, and review status."
    ),
)
def list_recommendations(
    namespace: Optional[str] = Query(
        default=None,
        description="Filter by Kubernetes namespace",
    ),
    workload_type: Optional[str] = Query(
        default=None,
        description="Filter by workload kind: Deployment, Pod, etc.",
    ),
    workload_name: Optional[str] = Query(
        default=None,
        description="Filter by workload name",
    ),
    recommendation_type: Optional[str] = Query(
        default=None,
        description="Filter by recommendation type (e.g. cpu_underutilization, memory_underutilization)",
    ),
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by review status: pending, applied, dismissed",
    ),
    cluster_id: Optional[str] = Query(
        default=None,
        description="Filter by cluster identifier",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> ApiResponse[List[ResourceRecommendationRead]]:
    """List and filter resource recommendations."""
    query = select(ResourceRecommendation)

    if namespace:
        query = query.where(ResourceRecommendation.namespace == namespace)
    if workload_type:
        query = query.where(ResourceRecommendation.workload_type == workload_type)
    if workload_name:
        query = query.where(ResourceRecommendation.workload_name == workload_name)
    if recommendation_type:
        query = query.where(ResourceRecommendation.recommendation_type == recommendation_type)
    if status_filter:
        # Match both frontend 'open' and database 'pending'
        val = status_filter.lower()
        if val == "open":
            val = "pending"
        query = query.where(ResourceRecommendation.review_status == val)
    if cluster_id:
        query = query.where(ResourceRecommendation.cluster_id == cluster_id)

    query = query.order_by(ResourceRecommendation.created_at.desc()).limit(limit).offset(offset)
    results = db.scalars(query).all()
    records = [ResourceRecommendationRead.model_validate(r) for r in results]

    return ApiResponse(
        status="ok",
        data=records,
    )


@router.get(
    "/recommendations/{recommendation_id}",
    response_model=ApiResponse[ResourceRecommendationRead],
    summary="Retrieve recommendation details",
    description="Returns full telemetry, current spec, suggested target, and rationale for a recommendation.",
)
def get_recommendation(
    recommendation_id: str,
    db: Session = Depends(get_db),
) -> ApiResponse[ResourceRecommendationRead]:
    """Retrieve details for a specific recommendation by ID."""
    rec = db.get(ResourceRecommendation, recommendation_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation {recommendation_id!r} not found",
        )
    return ApiResponse(
        status="ok",
        data=ResourceRecommendationRead.model_validate(rec),
    )


@router.patch(
    "/recommendations/{recommendation_id}",
    response_model=ApiResponse[ResourceRecommendationRead],
    summary="Update recommendation review status",
    description="Update review status to 'applied', 'dismissed', or 'pending'.",
)
@router.post(
    "/recommendations/{recommendation_id}/status",
    response_model=ApiResponse[ResourceRecommendationRead],
    summary="Update recommendation review status (POST alias)",
)
def update_recommendation_status(
    recommendation_id: str,
    payload: ResourceRecommendationUpdate,
    db: Session = Depends(get_db),
) -> ApiResponse[ResourceRecommendationRead]:
    """Update review status of a resource recommendation."""
    rec = db.get(ResourceRecommendation, recommendation_id)
    if not rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recommendation {recommendation_id!r} not found",
        )

    valid_statuses = {"pending", "applied", "dismissed"}
    new_status = payload.review_status.lower()
    if new_status == "open":
        new_status = "pending"

    if new_status not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid review status: {payload.review_status!r}. Must be one of {valid_statuses}.",
        )

    rec.review_status = new_status
    rec.updated_at = utc_now()
    db.commit()
    db.refresh(rec)

    return ApiResponse(
        status="ok",
        data=ResourceRecommendationRead.model_validate(rec),
    )


@router.post(
    "/recommendations/evaluate",
    response_model=ApiResponse[Dict[str, Any]],
    summary="Trigger an on-demand recommendation evaluation",
    description="Executes a live evaluation sweep against connected cluster telemetry and records results.",
)
async def trigger_evaluation(
    request: Request,
    db: Session = Depends(get_db),
) -> ApiResponse[Dict[str, Any]]:
    """Trigger on-demand recommendation evaluation across connected workloads."""
    settings = getattr(request.app.state, "settings", None) or get_settings()
    k8s = getattr(request.app.state, "kubernetes_service", None)
    prom = getattr(request.app.state, "prometheus_service", None)

    engine = RecommendationEngine(
        settings=settings,
        k8s_service=k8s,
        prom_service=prom,
    )

    candidates = await engine.evaluate_live()
    stats = engine.persist_recommendations(db, candidates)

    return ApiResponse(
        status="ok",
        data=stats,
    )
