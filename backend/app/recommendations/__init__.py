"""Recommendation engine package for KubeWatch."""

from app.recommendations.calculator import (
    MetricStatistics,
    RecommendationCandidate,
    WorkloadResourceSpec,
    calculate_metric_statistics,
    evaluate_cpu_underutilization,
    evaluate_high_memory_limit_utilization,
    evaluate_insufficient_historical_data,
    evaluate_memory_underutilization,
    format_cpu_millicores,
    format_memory_bytes,
)
from app.recommendations.config import RecommendationConfig
from app.recommendations.engine import RecommendationEngine

__all__ = [
    "MetricStatistics",
    "RecommendationCandidate",
    "RecommendationConfig",
    "RecommendationEngine",
    "WorkloadResourceSpec",
    "calculate_metric_statistics",
    "evaluate_cpu_underutilization",
    "evaluate_high_memory_limit_utilization",
    "evaluate_insufficient_historical_data",
    "evaluate_memory_underutilization",
    "format_cpu_millicores",
    "format_memory_bytes",
]

