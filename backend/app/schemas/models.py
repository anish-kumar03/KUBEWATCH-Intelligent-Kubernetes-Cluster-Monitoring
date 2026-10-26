"""Pydantic schemas for all API responses.

Every endpoint returns a typed schema.  Missing data is represented
as ``None`` (JSON ``null``), **never** as zero.

The ``ApiResponse`` wrapper provides a uniform envelope so the
frontend can distinguish successful data from errors without
inspecting HTTP status codes alone.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Generic API response envelope
# ---------------------------------------------------------------------------

DataT = TypeVar("DataT")


class ApiResponse(BaseModel, Generic[DataT]):
    """Uniform JSON envelope for every API response.

    ``status``
        ``"ok"`` when the request succeeded, ``"error"`` on failure.
    ``data``
        The payload; ``None`` when status is ``"error"``.
    ``error``
        Human-readable error description; ``None`` when status is ``"ok"``.
    ``timestamp``
        Server-side UTC timestamp of the response.
    """

    status: str = Field(..., examples=["ok", "error"])
    data: Optional[DataT] = None
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class ComponentHealth(BaseModel):
    """Connectivity status for a single backend dependency."""

    name: str
    healthy: bool
    message: Optional[str] = None


class HealthData(BaseModel):
    """Aggregated health check result."""

    healthy: bool
    components: List[ComponentHealth]


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


class NodeCondition(BaseModel):
    """A single Kubernetes node condition."""

    type: str
    status: str
    reason: Optional[str] = None
    message: Optional[str] = None


class NodeResources(BaseModel):
    """CPU and memory resource quantities for a node.

    Values are in Kubernetes quantity format (e.g. ``"4"`` for 4 cores,
    ``"8Gi"`` for 8 GiB).
    """

    cpu: Optional[str] = None
    memory: Optional[str] = None


class NodeInfo(BaseModel):
    """Summary of a single Kubernetes node."""

    name: str
    status: str = Field(..., description="Ready | NotReady | Unknown")
    roles: List[str] = Field(default_factory=list)
    capacity: NodeResources
    allocatable: NodeResources
    conditions: List[NodeCondition] = Field(default_factory=list)
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Pods
# ---------------------------------------------------------------------------


class ContainerResources(BaseModel):
    """Resource requests and limits for one container."""

    cpu_request: Optional[str] = None
    cpu_limit: Optional[str] = None
    memory_request: Optional[str] = None
    memory_limit: Optional[str] = None


class ContainerInfo(BaseModel):
    """Summary of a single container within a pod."""

    name: str
    image: str
    ready: bool = False
    restart_count: int = 0
    state: Optional[str] = None
    resources: ContainerResources = Field(default_factory=ContainerResources)


class PodInfo(BaseModel):
    """Summary of a single Kubernetes pod."""

    name: str
    namespace: str
    phase: str = Field(
        ..., description="Running | Pending | Succeeded | Failed | Unknown"
    )
    node_name: Optional[str] = None
    restart_count: int = 0
    containers: List[ContainerInfo] = Field(default_factory=list)
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Deployments
# ---------------------------------------------------------------------------


class DeploymentCondition(BaseModel):
    """A single Kubernetes deployment condition."""

    type: str
    status: str
    reason: Optional[str] = None
    message: Optional[str] = None


class DeploymentInfo(BaseModel):
    """Summary of a single Kubernetes deployment."""

    name: str
    namespace: str
    replicas: int = 0
    ready_replicas: int = 0
    available_replicas: int = 0
    unavailable_replicas: int = 0
    strategy: Optional[str] = None
    conditions: List[DeploymentCondition] = Field(default_factory=list)
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Cluster overview
# ---------------------------------------------------------------------------


class ClusterOverview(BaseModel):
    """Aggregated cluster-level summary."""

    node_count: int = 0
    pod_count: int = 0
    namespace_count: int = 0
    deployment_count: int = 0
    cpu_capacity: Optional[str] = None
    memory_capacity: Optional[str] = None
    # Utilisation from Prometheus (nullable when metrics are unavailable)
    cpu_usage_percent: Optional[float] = None
    memory_usage_percent: Optional[float] = None


# ---------------------------------------------------------------------------
# Metrics (Prometheus time-series)
# ---------------------------------------------------------------------------


class MetricDataPoint(BaseModel):
    """A single (timestamp, value) pair from Prometheus."""

    timestamp: float
    value: float


class MetricSeries(BaseModel):
    """A labelled time-series of data points."""

    metric_labels: dict[str, str] = Field(default_factory=dict)
    values: List[MetricDataPoint] = Field(default_factory=list)


class MetricsResult(BaseModel):
    """Container for one or more metric time-series.

    ``query_name``
        A human-readable identifier for the curated query that was
        executed (e.g. ``"node_cpu_usage_percent"``).
    ``series``
        The returned time-series.  Empty when Prometheus is
        unreachable or returns no data.
    ``error``
        Set when the metrics could not be retrieved.
    """

    query_name: str
    series: List[MetricSeries] = Field(default_factory=list)
    error: Optional[str] = None


class MetricsQueryParams(BaseModel):
    """Validated query parameters for metric endpoints.

    Used internally; not returned to the client.
    """

    namespace: Optional[str] = None
    pod: Optional[str] = None
    node: Optional[str] = None
    start: Optional[datetime] = None
    end: Optional[datetime] = None
    step: Optional[int] = None
