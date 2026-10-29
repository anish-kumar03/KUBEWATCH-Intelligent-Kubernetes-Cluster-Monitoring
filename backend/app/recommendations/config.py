"""Configuration settings for the KubeWatch recommendation engine."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RecommendationConfig(BaseModel):
    """Configurable thresholds, observation windows, and safety parameters for recommendations."""

    # Observation window
    observation_window_hours: int = Field(
        default=24,
        description="Historical observation window duration in hours.",
    )
    step_seconds: int = Field(
        default=300,  # 5 minutes
        description="Prometheus range query sampling step in seconds.",
    )

    # Minimum data sufficiency requirements
    min_observation_hours: float = Field(
        default=6.0,
        description="Minimum duration of telemetry history required before producing a sizing recommendation.",
    )
    min_samples_for_evaluation: int = Field(
        default=12,
        description="Minimum number of valid Prometheus samples required.",
    )
    min_samples_for_p95: int = Field(
        default=20,
        description="Minimum sample count required to compute a statistically sound p95 percentile.",
    )
    min_completeness_ratio: float = Field(
        default=0.50,
        description="Minimum ratio of collected samples to expected samples over the window (50%).",
    )

    # Underutilization thresholds (percent of configured request)
    cpu_underutilization_threshold_percent: float = Field(
        default=25.0,
        description="Threshold: workload is CPU underutilized if p95 usage is below this percentage of request.",
    )
    memory_underutilization_threshold_percent: float = Field(
        default=30.0,
        description="Threshold: workload is memory underutilized if peak usage is below this percentage of request.",
    )

    # Limit risk threshold (percent of configured limit)
    memory_limit_risk_threshold_percent: float = Field(
        default=85.0,
        description="Threshold: container is at risk of OOMKill if peak usage exceeds this percentage of memory limit.",
    )

    # Safety headroom multipliers applied to measured usage for suggested targets
    cpu_headroom_factor: float = Field(
        default=1.25,
        description="Safety headroom multiplier applied to p95/peak CPU usage (e.g. 1.25 = 25% buffer).",
    )
    memory_headroom_factor: float = Field(
        default=1.25,
        description="Safety headroom multiplier applied to peak memory usage.",
    )

    # Absolute lower floors
    min_cpu_floor_millicores: int = Field(
        default=50,
        description="Minimum allowable recommended CPU request in millicores (50m).",
    )
    min_memory_floor_bytes: int = Field(
        default=64 * 1024 * 1024,  # 64 MiB
        description="Minimum allowable recommended memory request in bytes (64 MiB).",
    )

