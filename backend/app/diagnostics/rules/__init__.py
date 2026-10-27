"""Export all KubeWatch diagnostic rules."""

from __future__ import annotations

from app.diagnostics.rules.deployment_availability import DeploymentAvailabilityRule
from app.diagnostics.rules.memory_utilization import HighMemoryUtilizationRule
from app.diagnostics.rules.node_pressure import NodePressureRule
from app.diagnostics.rules.pending_pod import PendingPodRule
from app.diagnostics.rules.restart_activity import IncreasedRestartActivityRule

ALL_RULES = [
    IncreasedRestartActivityRule(),
    PendingPodRule(),
    DeploymentAvailabilityRule(),
    HighMemoryUtilizationRule(),
    NodePressureRule(),
]

__all__ = [
    "ALL_RULES",
    "IncreasedRestartActivityRule",
    "PendingPodRule",
    "DeploymentAvailabilityRule",
    "HighMemoryUtilizationRule",
    "NodePressureRule",
]

