"""Statistical calculations, metrics validation, and recommendation heuristics."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.recommendations.config import RecommendationConfig
from app.services.kubernetes_service import _parse_cpu, _parse_memory


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_cpu_millicores(millicores: int) -> str:
    """Format millicores to Kubernetes quantity string (e.g. 500m or 2)."""
    if millicores >= 1000 and millicores % 1000 == 0:
        return f"{millicores // 1000}"
    return f"{millicores}m"


def format_memory_bytes(bytes_val: int) -> str:
    """Format bytes to human-readable Kubernetes MiB/GiB quantity string."""
    mebibytes = bytes_val / (1024 * 1024)
    if mebibytes >= 1024 and mebibytes % 1024 == 0:
        return f"{int(mebibytes // 1024)}Gi"
    return f"{round(mebibytes)}Mi"


class MetricStatistics(BaseModel):
    """Summarized historical metric observations for an evaluated workload."""

    sample_count: int = 0
    expected_samples: int = 0
    completeness_ratio: float = 0.0
    completeness_percent: float = 0.0
    duration_seconds: float = 0.0
    duration_hours: float = 0.0
    avg_value: Optional[float] = None
    p95_value: Optional[float] = None
    peak_value: Optional[float] = None
    is_sufficient: bool = False
    insufficiency_reason: Optional[str] = None


def calculate_metric_statistics(
    data_points: List[float],
    start_time: datetime,
    end_time: datetime,
    config: RecommendationConfig,
) -> MetricStatistics:
    """Compute statistically sound summary metrics with strict sufficiency checks.
    
    Never interprets missing data as zero. Discloses observation window and sample counts.
    """
    duration_seconds = max(1.0, (end_time - start_time).total_seconds())
    duration_hours = round(duration_seconds / 3600.0, 2)
    expected_samples = max(1, int(duration_seconds / config.step_seconds))
    sample_count = len(data_points)
    completeness_ratio = min(1.0, sample_count / expected_samples)
    completeness_percent = round(completeness_ratio * 100.0, 1)

    if sample_count == 0:
        return MetricStatistics(
            sample_count=0,
            expected_samples=expected_samples,
            completeness_ratio=0.0,
            completeness_percent=0.0,
            duration_seconds=duration_seconds,
            duration_hours=duration_hours,
            is_sufficient=False,
            insufficiency_reason="Zero metric samples collected over the observation window.",
        )

    min_observation_seconds = config.min_observation_hours * 3600.0
    if duration_seconds < min_observation_seconds:
        return MetricStatistics(
            sample_count=sample_count,
            expected_samples=expected_samples,
            completeness_ratio=completeness_ratio,
            completeness_percent=completeness_percent,
            duration_seconds=duration_seconds,
            duration_hours=duration_hours,
            avg_value=round(sum(data_points) / sample_count, 4),
            peak_value=round(max(data_points), 4),
            is_sufficient=False,
            insufficiency_reason=(
                f"Observation window ({duration_hours:.1f}h) is shorter than the required "
                f"minimum ({config.min_observation_hours:.1f}h)."
            ),
        )

    if sample_count < config.min_samples_for_evaluation:
        return MetricStatistics(
            sample_count=sample_count,
            expected_samples=expected_samples,
            completeness_ratio=completeness_ratio,
            completeness_percent=completeness_percent,
            duration_seconds=duration_seconds,
            duration_hours=duration_hours,
            avg_value=round(sum(data_points) / sample_count, 4),
            peak_value=round(max(data_points), 4),
            is_sufficient=False,
            insufficiency_reason=(
                f"Sample count ({sample_count}) is below required minimum threshold "
                f"({config.min_samples_for_evaluation})."
            ),
        )

    if completeness_ratio < config.min_completeness_ratio:
        return MetricStatistics(
            sample_count=sample_count,
            expected_samples=expected_samples,
            completeness_ratio=completeness_ratio,
            completeness_percent=completeness_percent,
            duration_seconds=duration_seconds,
            duration_hours=duration_hours,
            avg_value=round(sum(data_points) / sample_count, 4),
            peak_value=round(max(data_points), 4),
            is_sufficient=False,
            insufficiency_reason=(
                f"Data completeness ({completeness_percent}%) is below required threshold "
                f"({config.min_completeness_ratio * 100:.1f}%)."
            ),
        )

    # Valid, statistically sufficient observation
    avg_value = round(sum(data_points) / sample_count, 4)
    peak_value = round(max(data_points), 4)

    # Compute p95 where sample count allows
    p95_value = None
    if sample_count >= config.min_samples_for_p95:
        sorted_vals = sorted(data_points)
        idx = 0.95 * (sample_count - 1)
        lower = int(idx)
        upper = min(sample_count - 1, lower + 1)
        weight = idx - lower
        p95_value = round(sorted_vals[lower] * (1.0 - weight) + sorted_vals[upper] * weight, 4)

    return MetricStatistics(
        sample_count=sample_count,
        expected_samples=expected_samples,
        completeness_ratio=completeness_ratio,
        completeness_percent=completeness_percent,
        duration_seconds=duration_seconds,
        duration_hours=duration_hours,
        avg_value=avg_value,
        p95_value=p95_value,
        peak_value=peak_value,
        is_sufficient=True,
        insufficiency_reason=None,
    )


class WorkloadResourceSpec(BaseModel):
    """Configured resource limits and requests for a workload container."""

    container_name: str
    cpu_request_str: Optional[str] = None
    cpu_request_millicores: Optional[int] = None
    cpu_limit_str: Optional[str] = None
    cpu_limit_millicores: Optional[int] = None
    memory_request_str: Optional[str] = None
    memory_request_bytes: Optional[int] = None
    memory_limit_str: Optional[str] = None
    memory_limit_bytes: Optional[int] = None

    @classmethod
    def from_container_resources(
        cls,
        container_name: str,
        cpu_request: Optional[str],
        cpu_limit: Optional[str],
        memory_request: Optional[str],
        memory_limit: Optional[str],
    ) -> WorkloadResourceSpec:
        return cls(
            container_name=container_name,
            cpu_request_str=cpu_request,
            cpu_request_millicores=_parse_cpu(cpu_request) if cpu_request else None,
            cpu_limit_str=cpu_limit,
            cpu_limit_millicores=_parse_cpu(cpu_limit) if cpu_limit else None,
            memory_request_str=memory_request,
            memory_request_bytes=_parse_memory(memory_request) if memory_request else None,
            memory_limit_str=memory_limit,
            memory_limit_bytes=_parse_memory(memory_limit) if memory_limit else None,
        )


class RecommendationCandidate(BaseModel):
    """An advisory recommendation candidate generated by the recommendation engine."""

    cluster_id: str = "default"
    namespace: str
    workload_type: str  # Deployment, StatefulSet, DaemonSet
    workload_name: str
    container_name: Optional[str] = None
    recommendation_type: str  # cpu_underutilization, memory_underutilization, high_memory_limit_utilization, insufficient_historical_data
    observation_window: str = "24h"
    current_configuration: Dict[str, Any] = Field(default_factory=dict)
    measured_usage: Dict[str, Any] = Field(default_factory=dict)
    recommendation_text: str

    @property
    def fingerprint(self) -> str:
        """Deterministic UUID ensuring idempotent persistence and review tracking."""
        seed = (
            f"rec:{self.cluster_id}:{self.namespace}:{self.workload_type}:"
            f"{self.workload_name}:{self.container_name or ''}:{self.recommendation_type}"
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def evaluate_cpu_underutilization(
    cluster_id: str,
    namespace: str,
    workload_type: str,
    workload_name: str,
    spec: WorkloadResourceSpec,
    cpu_stats: MetricStatistics,
    config: RecommendationConfig,
) -> Optional[RecommendationCandidate]:
    """Evaluate whether configured CPU request is persistently underutilized."""
    if not cpu_stats.is_sufficient or spec.cpu_request_millicores is None or spec.cpu_request_millicores <= 0:
        return None

    # Benchmark against p95 (or peak if sample count for p95 was not reached)
    eval_cores = cpu_stats.p95_value if cpu_stats.p95_value is not None else cpu_stats.peak_value
    if eval_cores is None:
        return None

    eval_millicores = int(eval_cores * 1000)
    utilization_percent = round((eval_millicores / spec.cpu_request_millicores) * 100.0, 1)

    if utilization_percent >= config.cpu_underutilization_threshold_percent:
        return None

    # Calculate recommended target with safety headroom factor and floor
    target_millicores = max(
        config.min_cpu_floor_millicores,
        int(eval_millicores * config.cpu_headroom_factor),
    )

    freed_millicores = spec.cpu_request_millicores - target_millicores
    if freed_millicores <= 0:
        return None

    reduction_percent = round((freed_millicores / spec.cpu_request_millicores) * 100.0, 1)
    target_str = format_cpu_millicores(target_millicores)
    freed_str = format_cpu_millicores(freed_millicores)

    current_config = {
        "container_name": spec.container_name,
        "cpu_request": spec.cpu_request_str,
        "cpu_limit": spec.cpu_limit_str or "unconfigured",
        "spec": {
            "cpu_request": spec.cpu_request_str or "unconfigured",
        },
        "recommended_spec": {
            "cpu_request": target_str,
        },
    }

    measured_usage = {
        "avg_cpu_millicores": int((cpu_stats.avg_value or 0) * 1000),
        "p95_cpu_millicores": eval_millicores,
        "peak_cpu_millicores": int((cpu_stats.peak_value or 0) * 1000),
        "cpu_request_millicores": spec.cpu_request_millicores,
        "utilization_percent": utilization_percent,
        "observation_duration_hours": cpu_stats.duration_hours,
        "sample_count": cpu_stats.sample_count,
        "expected_samples": cpu_stats.expected_samples,
        "completeness_percent": cpu_stats.completeness_percent,
        "headroom_factor": config.cpu_headroom_factor,
        "freed_cpu_millicores": freed_millicores,
        "resource_reduction_summary": f"Frees {freed_str} of allocatable node CPU ({reduction_percent}% reduction in request)",
    }

    narrative = (
        f"### Workload & Container\n"
        f"Workload `{workload_type}/{namespace}/{workload_name}` (container `{spec.container_name}`).\n\n"
        f"### Observation Period & Telemetry\n"
        f"- Observation duration: {cpu_stats.duration_hours} hours ({cpu_stats.sample_count} valid samples, {cpu_stats.completeness_percent}% data completeness).\n"
        f"- Measured CPU usage: average {measured_usage['avg_cpu_millicores']}m, p95 {eval_millicores}m, peak {measured_usage['peak_cpu_millicores']}m.\n\n"
        f"### Current Configuration vs Measured Utilization\n"
        f"- Configured CPU request: `{spec.cpu_request_str}` ({spec.cpu_request_millicores}m).\n"
        f"- Workload consumed only {utilization_percent}% of its reserved CPU request at p95 over the observation period.\n\n"
        f"### Proposed Action\n"
        f"- Right-size CPU request from `{spec.cpu_request_str}` to `{target_str}` (includes {int((config.cpu_headroom_factor - 1.0) * 100)}% safety headroom above measured p95).\n"
        f"- Frees {freed_str} of cluster allocatable CPU capacity for other workloads.\n\n"
        f"### Assumptions & Risk Assessment\n"
        f"- Assumes observed {cpu_stats.duration_hours}h window captures typical peak workload traffic without pending batch spikes.\n"
        f"- Cost Disclaimer: Reducing CPU requests increases pod scheduling density and frees node allocatable capacity; cloud billing reduction depends on whether overall cluster node count can be downscaled."
    )

    return RecommendationCandidate(
        cluster_id=cluster_id,
        namespace=namespace,
        workload_type=workload_type,
        workload_name=workload_name,
        container_name=spec.container_name,
        recommendation_type="cpu_underutilization",
        observation_window=f"{int(cpu_stats.duration_hours)}h",
        current_configuration=current_config,
        measured_usage=measured_usage,
        recommendation_text=narrative,
    )


def evaluate_memory_underutilization(
    cluster_id: str,
    namespace: str,
    workload_type: str,
    workload_name: str,
    spec: WorkloadResourceSpec,
    mem_stats: MetricStatistics,
    config: RecommendationConfig,
) -> Optional[RecommendationCandidate]:
    """Evaluate whether configured memory request is persistently underutilized."""
    if not mem_stats.is_sufficient or spec.memory_request_bytes is None or spec.memory_request_bytes <= 0:
        return None

    if mem_stats.peak_value is None:
        return None

    peak_bytes = int(mem_stats.peak_value)
    utilization_percent = round((peak_bytes / spec.memory_request_bytes) * 100.0, 1)

    if utilization_percent >= config.memory_underutilization_threshold_percent:
        return None

    target_bytes = max(
        config.min_memory_floor_bytes,
        int(peak_bytes * config.memory_headroom_factor),
    )

    freed_bytes = spec.memory_request_bytes - target_bytes
    if freed_bytes <= 0:
        return None

    reduction_percent = round((freed_bytes / spec.memory_request_bytes) * 100.0, 1)
    target_str = format_memory_bytes(target_bytes)
    freed_str = format_memory_bytes(freed_bytes)

    current_config = {
        "container_name": spec.container_name,
        "memory_request": spec.memory_request_str,
        "memory_limit": spec.memory_limit_str or "unconfigured",
        "spec": {
            "memory_request": spec.memory_request_str or "unconfigured",
        },
        "recommended_spec": {
            "memory_request": target_str,
        },
    }

    measured_usage = {
        "avg_memory_bytes": int(mem_stats.avg_value or 0),
        "p95_memory_bytes": int(mem_stats.p95_value) if mem_stats.p95_value is not None else None,
        "peak_memory_bytes": peak_bytes,
        "memory_request_bytes": spec.memory_request_bytes,
        "utilization_percent": utilization_percent,
        "observation_duration_hours": mem_stats.duration_hours,
        "sample_count": mem_stats.sample_count,
        "expected_samples": mem_stats.expected_samples,
        "completeness_percent": mem_stats.completeness_percent,
        "headroom_factor": config.memory_headroom_factor,
        "freed_memory_bytes": freed_bytes,
        "resource_reduction_summary": f"Frees {freed_str} of allocatable node memory ({reduction_percent}% reduction in request)",
    }

    narrative = (
        f"### Workload & Container\n"
        f"Workload `{workload_type}/{namespace}/{workload_name}` (container `{spec.container_name}`).\n\n"
        f"### Observation Period & Telemetry\n"
        f"- Observation duration: {mem_stats.duration_hours} hours ({mem_stats.sample_count} valid samples, {mem_stats.completeness_percent}% data completeness).\n"
        f"- Measured working set: average {format_memory_bytes(int(mem_stats.avg_value or 0))}, peak {format_memory_bytes(peak_bytes)}.\n\n"
        f"### Current Configuration vs Measured Utilization\n"
        f"- Configured memory request: `{spec.memory_request_str}` ({format_memory_bytes(spec.memory_request_bytes)}).\n"
        f"- Container utilized only {utilization_percent}% of its memory request at peak over the entire window.\n\n"
        f"### Proposed Action\n"
        f"- Right-size memory request from `{spec.memory_request_str}` to `{target_str}` (includes {int((config.memory_headroom_factor - 1.0) * 100)}% safety buffer above peak working set).\n"
        f"- Frees {freed_str} of cluster allocatable memory for other workloads.\n\n"
        f"### Assumptions & Risk Assessment\n"
        f"- Unlike CPU, memory cannot be dynamically throttled; reducing memory requests requires verifying that the container does not experience unobserved memory allocation bursts."
    )

    return RecommendationCandidate(
        cluster_id=cluster_id,
        namespace=namespace,
        workload_type=workload_type,
        workload_name=workload_name,
        container_name=spec.container_name,
        recommendation_type="memory_underutilization",
        observation_window=f"{int(mem_stats.duration_hours)}h",
        current_configuration=current_config,
        measured_usage=measured_usage,
        recommendation_text=narrative,
    )


def evaluate_high_memory_limit_utilization(
    cluster_id: str,
    namespace: str,
    workload_type: str,
    workload_name: str,
    spec: WorkloadResourceSpec,
    mem_stats: MetricStatistics,
    config: RecommendationConfig,
) -> Optional[RecommendationCandidate]:
    """Evaluate whether container working set approaches memory limit risking OOMKill."""
    if mem_stats.sample_count == 0 or spec.memory_limit_bytes is None or spec.memory_limit_bytes <= 0:
        return None

    if mem_stats.peak_value is None:
        return None

    peak_bytes = int(mem_stats.peak_value)
    limit_utilization_percent = round((peak_bytes / spec.memory_limit_bytes) * 100.0, 1)

    if limit_utilization_percent < config.memory_limit_risk_threshold_percent:
        return None

    target_limit_bytes = int(peak_bytes * config.memory_headroom_factor)
    target_str = format_memory_bytes(target_limit_bytes)

    current_config = {
        "container_name": spec.container_name,
        "memory_limit": spec.memory_limit_str,
        "memory_request": spec.memory_request_str or "unconfigured",
        "spec": {
            "memory_limit": spec.memory_limit_str,
        },
        "recommended_spec": {
            "memory_limit": target_str,
        },
    }

    measured_usage = {
        "peak_memory_bytes": peak_bytes,
        "memory_limit_bytes": spec.memory_limit_bytes,
        "limit_utilization_percent": limit_utilization_percent,
        "sample_count": mem_stats.sample_count,
        "duration_hours": mem_stats.duration_hours,
        "headroom_factor": config.memory_headroom_factor,
        "resource_reduction_summary": None,  # Expanding limit, not saving
    }

    narrative = (
        f"### Workload & Container\n"
        f"Workload `{workload_type}/{namespace}/{workload_name}` (container `{spec.container_name}`).\n\n"
        f"### Observation Period & Telemetry\n"
        f"- Observation duration: {mem_stats.duration_hours} hours ({mem_stats.sample_count} samples).\n"
        f"- Measured peak memory working set: {format_memory_bytes(peak_bytes)}.\n\n"
        f"### Current Configuration vs Measured Utilization\n"
        f"- Configured memory limit: `{spec.memory_limit_str}` ({format_memory_bytes(spec.memory_limit_bytes)}).\n"
        f"- Container reached {limit_utilization_percent}% of its memory limit, approaching the kernel OOM termination boundary.\n\n"
        f"### Proposed Action\n"
        f"- Increase container memory limit from `{spec.memory_limit_str}` to `{target_str}` to provide safety headroom and avoid container restart loops.\n\n"
        f"### Assumptions & Risk Assessment\n"
        f"- Assumes high memory utilization is legitimate workload demand rather than an unbounded memory leak. Verify application heap behavior before increasing limits."
    )

    return RecommendationCandidate(
        cluster_id=cluster_id,
        namespace=namespace,
        workload_type=workload_type,
        workload_name=workload_name,
        container_name=spec.container_name,
        recommendation_type="high_memory_limit_utilization",
        observation_window=f"{int(mem_stats.duration_hours)}h",
        current_configuration=current_config,
        measured_usage=measured_usage,
        recommendation_text=narrative,
    )


def evaluate_insufficient_historical_data(
    cluster_id: str,
    namespace: str,
    workload_type: str,
    workload_name: str,
    spec: WorkloadResourceSpec,
    stats: MetricStatistics,
    metric_name: str,
    config: RecommendationConfig,
) -> RecommendationCandidate:
    """Produce an advisory notice when telemetry is insufficient for sizing recommendations."""
    current_config = {
        "container_name": spec.container_name,
        "cpu_request": spec.cpu_request_str or "unconfigured",
        "cpu_limit": spec.cpu_limit_str or "unconfigured",
        "memory_request": spec.memory_request_str or "unconfigured",
        "memory_limit": spec.memory_limit_str or "unconfigured",
        "spec": {
            "status": "observation_in_progress",
        },
        "recommended_spec": {},
    }

    measured_usage = {
        "metric_name": metric_name,
        "sample_count": stats.sample_count,
        "expected_samples": stats.expected_samples,
        "completeness_percent": stats.completeness_percent,
        "duration_hours": stats.duration_hours,
        "min_required_hours": config.min_observation_hours,
        "min_required_samples": config.min_samples_for_evaluation,
        "insufficiency_reason": stats.insufficiency_reason or "Insufficient telemetry history.",
        "resource_reduction_summary": None,
    }

    narrative = (
        f"### Workload & Container\n"
        f"Workload `{workload_type}/{namespace}/{workload_name}` (container `{spec.container_name}`).\n\n"
        f"### Advisory: Insufficient Historical Observations\n"
        f"KubeWatch cannot safely produce resource sizing recommendations for this workload due to incomplete historical telemetry:\n"
        f"- Reason: {stats.insufficiency_reason}\n"
        f"- Observations collected: {stats.sample_count} sample(s) over {stats.duration_hours}h ({stats.completeness_percent}% completeness).\n"
        f"- Required minimum: {config.min_observation_hours} hours and {config.min_samples_for_evaluation} samples.\n\n"
        f"### Proposed Action\n"
        f"- Allow the workload to run across a complete operational window ({config.observation_window_hours}h) before adjusting resource requests or limits.\n\n"
        f"### Assumptions & Risk Assessment\n"
        f"- Prematurely sizing containers on truncated observations risks underestimating burst traffic, peak memory allocation, or initialization overhead."
    )

    return RecommendationCandidate(
        cluster_id=cluster_id,
        namespace=namespace,
        workload_type=workload_type,
        workload_name=workload_name,
        container_name=spec.container_name,
        recommendation_type="insufficient_historical_data",
        observation_window=f"{int(stats.duration_hours)}h",
        current_configuration=current_config,
        measured_usage=measured_usage,
        recommendation_text=narrative,
    )

