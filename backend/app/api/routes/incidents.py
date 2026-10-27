"""Incidents endpoints — list, filter, retrieve details, acknowledge, and resolve."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.incident import Incident
from app.schemas.models import ApiResponse
from app.schemas.persistence import IncidentRead

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/incidents",
    response_model=ApiResponse[List[IncidentRead]],
    summary="List and filter operational incidents",
    description=(
        "Returns detected incidents ordered by severity (critical first) and recency. "
        "Supports filtering by status (active, acknowledged, resolved), severity, "
        "namespace, and resource type."
    ),
)
def list_incidents(
    status_filter: Optional[str] = Query(
        default=None,
        alias="status",
        description="Filter by incident status: active, acknowledged, resolved",
    ),
    severity: Optional[str] = Query(
        default=None,
        description="Filter by severity: critical, warning, info",
    ),
    namespace: Optional[str] = Query(
        default=None,
        description="Filter by Kubernetes namespace",
    ),
    resource_type: Optional[str] = Query(
        default=None,
        description="Filter by resource type: Pod, Deployment, Node",
    ),
    rule_identifier: Optional[str] = Query(
        default=None,
        description="Filter by detection rule identifier",
    ),
    cluster_id: Optional[str] = Query(
        default=None,
        description="Filter by cluster identifier",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="Page limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> ApiResponse[List[IncidentRead]]:
    """List and filter detected incidents."""
    query = select(Incident)

    if status_filter:
        query = query.where(Incident.status == status_filter.lower())
    if severity:
        query = query.where(Incident.severity == severity.lower())
    if namespace:
        query = query.where(Incident.namespace == namespace)
    if resource_type:
        query = query.where(Incident.resource_type == resource_type)
    if rule_identifier:
        query = query.where(Incident.rule_identifier == rule_identifier)
    if cluster_id:
        query = query.where(Incident.cluster_id == cluster_id)

    # Order by severity priority (critical=1, warning=2, info=3) then recency
    severity_order = case(
        (Incident.severity == "critical", 1),
        (Incident.severity == "warning", 2),
        (Incident.severity == "info", 3),
        else_=4,
    )

    query = (
        query.order_by(severity_order, Incident.last_observed_at.desc())
        .limit(limit)
        .offset(offset)
    )

    results = db.scalars(query).all()
    records = [IncidentRead.model_validate(r) for r in results]

    return ApiResponse(
        status="ok",
        data=records,
    )


@router.get(
    "/incidents/{incident_id}",
    response_model=ApiResponse[IncidentRead],
    summary="Retrieve incident details",
    description="Returns full incident details with supporting normalized evidence.",
)
def get_incident(
    incident_id: str,
    db: Session = Depends(get_db),
) -> ApiResponse[IncidentRead]:
    """Retrieve a single incident by ID."""
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {incident_id!r} not found.",
        )

    return ApiResponse(
        status="ok",
        data=IncidentRead.model_validate(incident),
    )


@router.post(
    "/incidents/{incident_id}/acknowledge",
    response_model=ApiResponse[IncidentRead],
    summary="Acknowledge an incident",
    description="Transitions an active incident to acknowledged status indicating operator awareness.",
)
def acknowledge_incident(
    incident_id: str,
    db: Session = Depends(get_db),
) -> ApiResponse[IncidentRead]:
    """Acknowledge an active incident."""
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {incident_id!r} not found.",
        )

    if incident.status == "resolved":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot acknowledge an already resolved incident.",
        )

    incident.status = "acknowledged"
    db.commit()
    db.refresh(incident)

    return ApiResponse(
        status="ok",
        data=IncidentRead.model_validate(incident),
    )


@router.post(
    "/incidents/{incident_id}/resolve",
    response_model=ApiResponse[IncidentRead],
    summary="Resolve an incident",
    description="Manually marks an incident as resolved with resolution timestamp.",
)
def resolve_incident(
    incident_id: str,
    db: Session = Depends(get_db),
) -> ApiResponse[IncidentRead]:
    """Resolve an open or acknowledged incident."""
    incident = db.get(Incident, incident_id)
    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident with ID {incident_id!r} not found.",
        )

    if incident.status != "resolved":
        incident.status = "resolved"
        incident.resolution_time = datetime.now(timezone.utc)
        db.commit()
        db.refresh(incident)

    return ApiResponse(
        status="ok",
        data=IncidentRead.model_validate(incident),
    )


@router.post(
    "/incidents/sweep",
    response_model=ApiResponse[Dict[str, Any]],
    summary="Trigger diagnostic sweep on demand",
    description="Triggers an immediate evaluation run of all diagnostic rules.",
)
async def trigger_sweep(request: Request) -> ApiResponse[Dict[str, Any]]:
    """Trigger an on-demand diagnostic sweep."""
    scheduler = getattr(request.app.state, "diagnostics_scheduler", None)
    if not scheduler:
        return ApiResponse(
            status="error",
            error="Diagnostics scheduler is not active on this backend.",
        )

    sweep_result = await scheduler.run_single_sweep()
    return ApiResponse(
        status="ok" if sweep_result.get("status") == "ok" else "error",
        data=sweep_result,
    )

