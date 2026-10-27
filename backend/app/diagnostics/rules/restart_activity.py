"""Detection rule: Increased container restart activity."""

from __future__ import annotations

from typing import Any, List

from app.diagnostics.base import (
    DiagnosticRule,
    EvaluationContext,
    EvidenceData,
    IncidentCandidate,
)


class IncreasedRestartActivityRule(DiagnosticRule):
    """Detects pods exhibiting elevated container restart counts or CrashLoopBackOff."""

    rule_identifier = "container-restart-activity"
    name = "Increased Container Restart Activity"
    description = (
        "Flags pods whose containers exceed a restart count threshold or are "
        "actively stuck in a CrashLoopBackOff state."
    )
    default_severity = "warning"
    default_thresholds = {
        "restart_threshold": 5,
        "critical_restart_threshold": 15,
    }

    def evaluate(self, context: EvaluationContext) -> List[IncidentCandidate]:
        if not self.is_enabled(context):
            return []

        restart_threshold = int(self.get_threshold(context, "restart_threshold", 5))
        critical_threshold = int(self.get_threshold(context, "critical_restart_threshold", 15))

        incidents: List[IncidentCandidate] = []

        for pod in context.pods:
            # Check containers within the pod
            failing_containers = []
            max_restarts = 0
            is_oom_killed = False

            for c in pod.containers:
                c_restarts = c.restart_count
                if c_restarts > max_restarts:
                    max_restarts = c_restarts

                state_lower = (c.state or "").lower()
                is_crashloop = "crashloop" in state_lower or "error" in state_lower
                if "oomkilled" in state_lower or "137" in state_lower:
                    is_oom_killed = True

                if c_restarts >= restart_threshold or (is_crashloop and c_restarts > 0):
                    failing_containers.append(c)

            if not failing_containers:
                continue

            # Determine severity
            severity = "critical" if (max_restarts >= critical_threshold or is_oom_killed) else "warning"

            # Build evidence
            evidence_items: List[EvidenceData] = []
            container_summaries = []

            for c in failing_containers:
                container_summaries.append(f"{c.name} ({c.restart_count} restarts, state: {c.state or 'unknown'})")
                evidence_items.append(
                    EvidenceData(
                        evidence_type="container_state",
                        summary=f"Container '{c.name}' has restarted {c.restart_count} times; state: {c.state or 'unknown'}",
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
                            "ready": c.ready,
                            "state": c.state,
                        },
                        relevant_configuration={
                            "restart_threshold": restart_threshold,
                            "critical_restart_threshold": critical_threshold,
                        },
                        explanation=(
                            f"Restart count {c.restart_count} meets or exceeds configured threshold "
                            f"{restart_threshold} or indicates crash looping."
                        ),
                    )
                )

            containers_str = ", ".join(container_summaries)
            what_observed = (
                f"Pod '{pod.name}' in namespace '{pod.namespace}' has elevated container restart activity. "
                f"Affected containers: {containers_str}. Pod phase is '{pod.phase}'."
            )
            why_flagged = (
                f"Container restart count reached {max_restarts}, exceeding the threshold of {restart_threshold} restarts. "
                + ("Container exit indicates OOMKilled termination. " if is_oom_killed else "")
                + "Frequent restarts indicate fatal unhandled exceptions, failed health probes, or resource exhaustion."
            )

            investigation_steps = [
                f"Check previous termination logs: kubectl logs {pod.name} -n {pod.namespace} --previous",
                f"Inspect container exit codes and event stream: kubectl describe pod {pod.name} -n {pod.namespace}",
                "Review application startup configuration, missing environment variables, or unreachable dependencies.",
            ]
            if is_oom_killed:
                investigation_steps.append(
                    "Container was terminated by OOM killer; review memory limits and evaluate KubeWatch right-sizing recommendations."
                )

            uncertainties = [
                "Root cause within the container process (e.g. fatal code exception vs failed liveness probe) requires log inspection.",
            ]

            candidate = IncidentCandidate(
                cluster_id=context.cluster_id,
                resource_type="Pod",
                namespace=pod.namespace,
                resource_name=pod.name,
                rule_identifier=self.rule_identifier,
                severity=severity,
                title=f"Pod {pod.name} has elevated container restart activity ({max_restarts} restarts)",
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

