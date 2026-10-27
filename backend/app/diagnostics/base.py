"""Base classes and normalized schemas for KubeWatch diagnostic rules."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field

from app.schemas.models import DeploymentInfo, NodeInfo, PodInfo


def utc_now() -> datetime:
    """Return current UTC timestamp with tzinfo."""
    return datetime.now(timezone.utc)


class EvidenceData(BaseModel):
    """Normalized evidence record supporting an incident diagnosis."""

    evidence_type: str = Field(
        ...,
        description="Type of evidence: container_state, pod_condition, replica_deficit, metric_breach, node_condition",
    )
    summary: str = Field(
        ...,
        description="Concise human-readable summary of the observed finding",
    )
    observation_time: datetime = Field(
        default_factory=utc_now,
        description="Timestamp when the observation occurred",
    )
    source_type: str = Field(
        ...,
        description="Source system of record: kubernetes_api, prometheus_metrics, or k8s_events",
    )
    affected_resource: Dict[str, Any] = Field(
        default_factory=dict,
        description="Resource coordinates: cluster_id, namespace, resource_type, resource_name, container",
    )
    measured_value: Dict[str, Any] = Field(
        default_factory=dict,
        description="Actual measured state or telemetry readings (e.g. restarts=8, exit_code=137)",
    )
    relevant_configuration: Dict[str, Any] = Field(
        default_factory=dict,
        description="Configured limits or thresholds that were compared (e.g. threshold=5, limit=512Mi)",
    )
    explanation: str = Field(
        ...,
        description="Specific rationale connecting the measured value to the rule threshold",
    )

    def to_source_metadata(self) -> Dict[str, Any]:
        """Convert normalized evidence payload to database JSON source_metadata."""
        return {
            "source_type": self.source_type,
            "affected_resource": self.affected_resource,
            "measured_value": self.measured_value,
            "relevant_configuration": self.relevant_configuration,
            "explanation": self.explanation,
        }


class IncidentCandidate(BaseModel):
    """An incident candidate identified by a diagnostic rule before persistence."""

    cluster_id: str = "default"
    resource_type: str = Field(..., description="Pod, Deployment, Node")
    namespace: Optional[str] = None
    resource_name: str
    rule_identifier: str
    severity: str = "warning"  # critical, warning, info
    title: str
    description: str

    # Explicit explainability structure
    what_observed: str
    why_flagged: str
    investigation_steps: List[str] = Field(default_factory=list)
    uncertainties: List[str] = Field(default_factory=list)

    # Evidence collection
    evidence: List[EvidenceData] = Field(default_factory=list)

    first_observed_at: datetime = Field(default_factory=utc_now)
    last_observed_at: datetime = Field(default_factory=utc_now)

    @property
    def fingerprint(self) -> str:
        """Deterministic UUID fingerprint ensuring idempotent incident persistence."""
        seed = (
            f"kubewatch:{self.cluster_id}:"
            f"{self.namespace or ''}:"
            f"{self.resource_type}:"
            f"{self.resource_name}:"
            f"{self.rule_identifier}"
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))

    def format_full_description(self) -> str:
        """Render a structured, explainable description separating facts from inferences."""
        steps_rendered = "\n".join(f"  {idx + 1}. {step}" for idx, step in enumerate(self.investigation_steps))
        uncertainties_rendered = (
            "\n".join(f"  - {u}" for u in self.uncertainties)
            if self.uncertainties
            else "  None noted at this evaluation stage."
        )

        return (
            f"### Observed Fact\n{self.what_observed}\n\n"
            f"### Trigger Rationale\n{self.why_flagged}\n\n"
            f"### Recommended Next Steps\n{steps_rendered}\n\n"
            f"### Limitations & Uncertainties\n{uncertainties_rendered}"
        )


class EvaluationContext(BaseModel):
    """Contextual cluster state and metrics supplied to diagnostic rules."""

    cluster_id: str = "default"
    nodes: List[NodeInfo] = Field(default_factory=list)
    pods: List[PodInfo] = Field(default_factory=list)
    deployments: List[DeploymentInfo] = Field(default_factory=list)
    # Memory metrics mapping: (namespace, pod) -> working_set_bytes
    pod_memory_bytes: Dict[Tuple[str, str], float] = Field(default_factory=dict)
    # Container memory metrics mapping: (namespace, pod, container) -> working_set_bytes
    container_memory_bytes: Dict[Tuple[str, str, str], float] = Field(default_factory=dict)
    # Timestamp of this evaluation sweep
    now: datetime = Field(default_factory=utc_now)
    # Dynamic rule configurations from DB/Settings
    rule_configs: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    # Source availability tracking (e.g. 'prometheus', 'k8s')
    unavailable_sources: Set[str] = Field(default_factory=set)

    model_config = {"arbitrary_types_allowed": True}


class DiagnosticRule(ABC):
    """Abstract base class for all deterministic diagnostic rules."""

    rule_identifier: str
    name: str
    description: str
    default_severity: str = "warning"
    default_thresholds: Dict[str, Any] = {}

    def is_enabled(self, context: EvaluationContext) -> bool:
        """Check if this rule is enabled in the current evaluation context."""
        cfg = context.rule_configs.get(self.rule_identifier)
        if cfg is not None and "enabled" in cfg:
            return bool(cfg["enabled"])
        return True

    def get_threshold(self, context: EvaluationContext, key: str, fallback: Any = None) -> Any:
        """Get a threshold value with precedence: context overrides -> defaults -> fallback."""
        cfg = context.rule_configs.get(self.rule_identifier, {})
        thresholds = cfg.get("threshold_config", {})
        if key in thresholds:
            return thresholds[key]
        if key in self.default_thresholds:
            return self.default_thresholds[key]
        return fallback

    @abstractmethod
    def evaluate(self, context: EvaluationContext) -> List[IncidentCandidate]:
        """Evaluate cluster context and return detected incident candidates."""
        pass

