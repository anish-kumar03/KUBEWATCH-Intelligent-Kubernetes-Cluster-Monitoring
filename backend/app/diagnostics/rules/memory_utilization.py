"""Detection rule: Sustained high memory utilization relative to configured container limit."""

from __future__ import annotations

from typing import List

from app.diagnostics.base import (
    DiagnosticRule,
    EvaluationContext,
    EvidenceData,
    IncidentCandidate,
)
from app.services.kubernetes_service import _parse_memory


class HighMemoryUtilizationRule(DiagnosticRule):
    """Detects containers whose working set memory approaches their configured memory limit."""

    rule_identifier = "container-memory-high-utilization"
    name = "High Memory Utilization Relative to Limit"
    description = (
        "Flags containers whose measured memory working set exceeds 85% of their "
        "configured memory limit, risking sudden kernel OOM termination."
    )
    default_severity = "warning"
    default_thresholds = {
        "memory_threshold_percent": 85.0,
        "critical_memory_threshold_percent": 95.0,
        "recovery_threshold_percent": 80.0,
    }

    def evaluate(self, context: EvaluationContext) -> List[IncidentCandidate]:
        if not self.is_enabled(context):
            return []

        # If Prometheus is down or unavailable, skip without throwing or falsely resolving
        if "prometheus" in context.unavailable_sources:
            return []

        warn_percent = float(self.get_threshold(context, "memory_threshold_percent", 85.0))
        crit_percent = float(self.get_threshold(context, "critical_memory_threshold_percent", 95.0))

        incidents: List[IncidentCandidate] = []

        for pod in context.pods:
            # Check containers with defined limits
            for c in pod.containers:
                limit_str = c.resources.memory_limit
                if not limit_str:
                    continue

                limit_bytes = _parse_memory(limit_str)
                if limit_bytes <= 0:
                    continue

                # Look up observed working set in context
                # Try container-level first, then pod-level
                measured_bytes = context.container_memory_bytes.get(
                    (pod.namespace, pod.name, c.name)
                )
                if measured_bytes is None:
                    # Fallback to pod-level if container-level is aggregated
                    measured_bytes = context.pod_memory_bytes.get((pod.namespace, pod.name))

                if measured_bytes is None or measured_bytes <= 0:
                    # Missing metric data for this container: skip
                    continue

                utilization_percent = round((measured_bytes / limit_bytes) * 100.0, 1)

                if utilization_percent < warn_percent:
                    continue

                severity = "critical" if utilization_percent >= crit_percent else "warning"

                used_mib = round(measured_bytes / (1024 * 1024), 1)
                limit_mib = round(limit_bytes / (1024 * 1024), 1)

                evidence_items = [
                    EvidenceData(
                        evidence_type="metric_breach",
                        summary=(
                            f"Container '{c.name}' memory working set reached {used_mib} MiB, "
                            f"which is {utilization_percent}% of its configured limit ({limit_mib} MiB)."
                        ),
                        observation_time=context.now,
                        source_type="prometheus_metrics",
                        affected_resource={
                            "cluster_id": context.cluster_id,
                            "namespace": pod.namespace,
                            "resource_type": "Pod",
                            "resource_name": pod.name,
                            "container_name": c.name,
                        },
                        measured_value={
                            "working_set_bytes": measured_bytes,
                            "working_set_mib": used_mib,
                            "utilization_percent": utilization_percent,
                            "promql_metric": "container_memory_working_set_bytes",
                        },
                        relevant_configuration={
                            "memory_limit_bytes": limit_bytes,
                            "memory_limit_str": limit_str,
                            "memory_limit_mib": limit_mib,
                            "threshold_percent": warn_percent,
                            "critical_threshold_percent": crit_percent,
                        },
                        explanation=(
                            f"Utilization ({utilization_percent}%) exceeds safety threshold of "
                            f"{warn_percent}%. When working set reaches 100% of memory limit, the Linux "
                            f"cgroup invokes OOM killer to terminate the container."
                        ),
                    )
                ]

                # Correlate with historical restarts or prior OOMKilled state
                state_str = (c.state or "").lower()
                if "oomkilled" in state_str or "137" in state_str:
                    evidence_items.append(
                        EvidenceData(
                            evidence_type="container_state",
                            summary=(
                                f"Correlated prior termination: Container '{c.name}' previously terminated "
                                f"due to OOMKilled (restart count: {c.restart_count})."
                            ),
                            observation_time=context.now,
                            source_type="kubernetes_api",
                            affected_resource={
                                "cluster_id": context.cluster_id,
                                "namespace": pod.namespace,
                                "resource_type": "Pod",
                                "resource_name": pod.name,
                                "container_name": c.name,
                            },
                            measured_value={
                                "restart_count": c.restart_count,
                                "state": c.state,
                            },
                            relevant_configuration={},
                            explanation="Container has already suffered OOM terminations and is once again approaching memory limit.",
                        )
                    )

                what_observed = (
                    f"Container '{c.name}' in pod '{pod.name}' (namespace '{pod.namespace}') has measured memory "
                    f"working set of {used_mib} MiB ({utilization_percent}% of limit {limit_mib} MiB)."
                )
                why_flagged = (
                    f"Memory utilization ({utilization_percent}%) exceeds the {warn_percent}% threshold. "
                    + ("Imminent risk of OOM termination (>95%). " if utilization_percent >= crit_percent else "")
                    + "Kubernetes cgroup enforcement terminates containers whose working set exceeds configured memory limits."
                )

                investigation_steps = [
                    f"Inspect container memory profiles or heap usage: kubectl top pod {pod.name} -n {pod.namespace} --containers",
                    "Check application logs for caching build-up, unbounded buffers, or memory leaks.",
                    f"Increase container memory limit in deployment specification (current limit: {limit_str}).",
                    "Review KubeWatch right-sizing recommendations for workload memory allocation.",
                ]

                uncertainties = [
                    "Active memory working set includes inactive file pages within cgroup; memory reclamation may free pages before hard OOM depending on kernel pressure.",
                ]

                candidate = IncidentCandidate(
                    cluster_id=context.cluster_id,
                    resource_type="Pod",
                    namespace=pod.namespace,
                    resource_name=pod.name,
                    rule_identifier=self.rule_identifier,
                    severity=severity,
                    title=f"Container {c.name} high memory utilization ({utilization_percent}% of limit)",
                    description="",
                    what_observed=what_observed,
                    why_flagged=why_flagged,
                    investigation_steps=investigation_steps,
                    uncertainties=uncertainties,
                    evidence=evidence_items,
                    first_observed_at=context.now,
                    last_observed_at=context.now,
                )
                candidate.description = candidate.format_full_description()
                incidents.append(candidate)

        return incidents

