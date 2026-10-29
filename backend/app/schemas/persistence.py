"""Pydantic schemas for persistence models: Incidents, Evidence, Recommendations, and Detection Rules."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field


# ---------------------------------------------------------------------------
# Incident Evidence Schemas
# ---------------------------------------------------------------------------

class IncidentEvidenceBase(BaseModel):
    """Base fields for incident evidence."""

    evidence_type: str = Field(..., description="metric_breach, k8s_event, log_pattern, condition_change")
    summary: str = Field(..., description="Human-readable summary of the observed evidence")
    observation_time: datetime = Field(..., description="Timestamp when evidence was observed")
    source_metadata: dict[str, Any] = Field(default_factory=dict, description="Structured metric/event data")


class IncidentEvidenceCreate(IncidentEvidenceBase):
    """Schema for adding evidence to an incident."""

    pass


class IncidentEvidenceRead(IncidentEvidenceBase):
    """Schema for reading incident evidence."""

    id: str
    incident_id: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Incident Schemas
# ---------------------------------------------------------------------------

class IncidentBase(BaseModel):
    """Base fields for an operational incident."""

    cluster_id: str = Field(default="default", description="Cluster identifier")
    resource_type: str = Field(..., description="Pod, Deployment, Node, etc.")
    namespace: Optional[str] = Field(default=None, description="Kubernetes namespace")
    resource_name: str = Field(..., description="Name of affected resource")
    rule_identifier: str = Field(..., description="Detection rule identifier that triggered the incident")
    severity: str = Field(default="warning", description="critical, warning, info")
    title: str = Field(..., description="Short incident summary title")
    description: str = Field(default="", description="Detailed incident description")
    first_observed_at: datetime = Field(..., description="First observed timestamp")
    last_observed_at: datetime = Field(..., description="Most recent observation timestamp")
    status: str = Field(default="active", description="active, acknowledged, resolved")
    resolution_time: Optional[datetime] = Field(default=None, description="Timestamp of resolution")


class IncidentCreate(IncidentBase):
    """Payload for creating a new incident."""

    id: Optional[str] = Field(default=None, description="Optional custom UUID")
    evidence: Optional[List[IncidentEvidenceCreate]] = Field(default_factory=list)


class IncidentUpdate(BaseModel):
    """Payload for updating an existing incident's status."""

    status: Optional[str] = None
    severity: Optional[str] = None
    description: Optional[str] = None
    last_observed_at: Optional[datetime] = None
    resolution_time: Optional[datetime] = None


class IncidentRead(IncidentBase):
    """Schema for reading an incident including evidence items."""

    id: str
    created_at: datetime
    updated_at: datetime
    evidence: List[IncidentEvidenceRead] = Field(default_factory=list)

    @computed_field
    def rule_name(self) -> str:
        """Alias rule_identifier to rule_name for UI display."""
        return self.rule_identifier

    @computed_field
    def message(self) -> str:
        """Human-readable message headline."""
        return self.title

    @computed_field
    def observed_at(self) -> datetime:
        """Observation timestamp compatible with frontend schema."""
        return self.last_observed_at

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Resource Recommendation Schemas
# ---------------------------------------------------------------------------

class ResourceRecommendationBase(BaseModel):
    """Base fields for resource rightsizing recommendations."""

    cluster_id: str = Field(default="default", description="Target cluster")
    namespace: str = Field(..., description="Kubernetes namespace")
    workload_type: str = Field(..., description="Deployment, StatefulSet, DaemonSet")
    workload_name: str = Field(..., description="Workload name")
    container_name: Optional[str] = Field(default=None, description="Target container if applicable")
    recommendation_type: str = Field(..., description="cpu_request, cpu_limit, memory_request, memory_limit, replica_count")
    observation_window: str = Field(default="7d", description="Lookback window duration")
    current_configuration: dict[str, Any] = Field(default_factory=dict, description="Current configuration summary")
    measured_usage: dict[str, Any] = Field(default_factory=dict, description="Observed usage telemetry summary")
    recommendation_text: str = Field(..., description="Actionable recommendation narrative")
    review_status: str = Field(default="pending", description="pending, applied, dismissed")


class ResourceRecommendationCreate(ResourceRecommendationBase):
    """Payload for recording a resource recommendation."""

    id: Optional[str] = None


class ResourceRecommendationUpdate(BaseModel):
    """Payload for updating recommendation review status."""

    review_status: str = Field(..., description="Updated review status: pending, applied, dismissed")


class ResourceRecommendationRead(ResourceRecommendationBase):
    """Schema for reading a resource recommendation."""

    id: str
    created_at: datetime
    updated_at: datetime

    @computed_field
    def status(self) -> str:
        """Map review_status to frontend expectation (pending -> open)."""
        if self.review_status == "pending":
            return "open"
        return self.review_status

    @computed_field
    def resource_type(self) -> str:
        """Resource type alias."""
        return self.workload_type

    @computed_field
    def current_spec(self) -> dict[str, str]:
        """Current resource specification summary."""
        spec = self.current_configuration.get("spec")
        if isinstance(spec, dict):
            return {str(k): str(v) for k, v in spec.items()}
        return {
            str(k): str(v)
            for k, v in self.current_configuration.items()
            if isinstance(v, (str, int, float)) and k not in ("recommended_spec",)
        }

    @computed_field
    def recommended_spec(self) -> dict[str, str]:
        """Recommended resource specification."""
        rec = self.current_configuration.get("recommended_spec")
        if isinstance(rec, dict):
            return {str(k): str(v) for k, v in rec.items()}
        return {}

    @computed_field
    def reasoning(self) -> str:
        """Rationale for the recommendation."""
        return self.recommendation_text

    @computed_field
    def estimated_savings(self) -> Optional[str]:
        """Resource capacity reduction summary (not monetary cost)."""
        return self.measured_usage.get("resource_reduction_summary")

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Detection Rule Schemas
# ---------------------------------------------------------------------------

class DetectionRuleBase(BaseModel):
    """Base fields for detection rules."""

    id: str = Field(..., description="Unique rule identifier slug")
    name: str = Field(..., description="Human-readable rule name")
    description: str = Field(default="", description="Rule description and symptoms")
    severity: str = Field(default="warning", description="critical, warning, info")
    enabled: bool = Field(default=True, description="Whether rule evaluation is active")
    threshold_config: dict[str, Any] = Field(default_factory=dict, description="Configurable threshold parameters")


class DetectionRuleCreate(DetectionRuleBase):
    """Payload for registering a detection rule."""

    pass


class DetectionRuleUpdate(BaseModel):
    """Payload for modifying an existing detection rule."""

    name: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    enabled: Optional[bool] = None
    threshold_config: Optional[dict[str, Any]] = None


class DetectionRuleRead(DetectionRuleBase):
    """Schema for reading a detection rule."""

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
