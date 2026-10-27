"""Detection rule: Pods remaining in Pending phase."""

from __future__ import annotations

from typing import List

from app.diagnostics.base import (
    DiagnosticRule,
    EvaluationContext,
    EvidenceData,
    IncidentCandidate,
)


class PendingPodRule(DiagnosticRule):
    """Detects pods that remain stuck in the Pending phase beyond an allowable duration."""

    rule_identifier = "pod-pending-duration"
    name = "Pods Remaining Pending"
    description = (
        "Flags pods that stay in the Pending phase without scheduling or initializing, "
        "indicating scheduling blocks, resource constraints, or storage binding failures."
    )
    default_severity = "warning"
    default_thresholds = {
        "pending_threshold_seconds": 300,        # 5 minutes
        "critical_pending_threshold_seconds": 900,  # 15 minutes
    }

    def evaluate(self, context: EvaluationContext) -> List[IncidentCandidate]:
        if not self.is_enabled(context):
            return []

        warn_threshold = int(self.get_threshold(context, "pending_threshold_seconds", 300))
        crit_threshold = int(self.get_threshold(context, "critical_pending_threshold_seconds", 900))

        incidents: List[IncidentCandidate] = []

        # Check for correlated node pressure across the cluster
        unready_or_pressured_nodes = [
            n.name
            for n in context.nodes
            if n.status != "Ready"
            or any(c.status == "True" for c in n.conditions if "pressure" in c.type.lower())
        ]

        for pod in context.pods:
            if pod.phase.lower() != "pending":
                continue

            # Determine duration
            if pod.created_at:
                elapsed_seconds = max(0, int((context.now - pod.created_at).total_seconds()))
            else:
                # If creation timestamp is missing, treat as satisfying minimum threshold if pending
                elapsed_seconds = warn_threshold

            if elapsed_seconds < warn_threshold:
                continue

            severity = "critical" if elapsed_seconds >= crit_threshold else "warning"

            evidence_items = [
                EvidenceData(
                    evidence_type="pod_condition",
                    summary=(
                        f"Pod '{pod.name}' has been in Pending phase for {elapsed_seconds}s "
                        f"(threshold: {warn_threshold}s); assigned node: {pod.node_name or 'none'}."
                    ),
                    observation_time=context.now,
                    source_type="kubernetes_api",
                    affected_resource={
                        "cluster_id": context.cluster_id,
                        "namespace": pod.namespace,
                        "resource_type": "Pod",
                        "resource_name": pod.name,
                    },
                    measured_value={
                        "phase": pod.phase,
                        "elapsed_seconds": elapsed_seconds,
                        "node_name": pod.node_name,
                        "container_count": len(pod.containers),
                    },
                    relevant_configuration={
                        "pending_threshold_seconds": warn_threshold,
                        "critical_pending_threshold_seconds": crit_threshold,
                    },
                    explanation=(
                        f"Pod pending duration ({elapsed_seconds}s) exceeds the configured threshold "
                        f"of {warn_threshold}s without transitioning to Running."
                    ),
                )
            ]

            if unready_or_pressured_nodes:
                evidence_items.append(
                    EvidenceData(
                        evidence_type="node_condition",
                        summary=(
                            f"Correlated cluster state: {len(unready_or_pressured_nodes)} node(s) "
                            f"are NotReady or reporting pressure ({', '.join(unready_or_pressured_nodes[:3])})."
                        ),
                        observation_time=context.now,
                        source_type="kubernetes_api",
                        affected_resource={
                            "cluster_id": context.cluster_id,
                            "resource_type": "Cluster",
                            "resource_name": context.cluster_id,
                        },
                        measured_value={"pressured_nodes": unready_or_pressured_nodes},
                        relevant_configuration={},
                        explanation="Available scheduling capacity is constrained by impaired cluster nodes.",
                    )
                )

            what_observed = (
                f"Pod '{pod.name}' in namespace '{pod.namespace}' has remained in Pending phase for {elapsed_seconds} seconds. "
                f"No container has reached Running status."
            )
            why_flagged = (
                f"Pending duration ({elapsed_seconds}s) exceeded the allowable threshold of {warn_threshold} seconds. "
                "Pending pods commonly stem from unschedulable CPU/memory requests, node affinity/taint mismatches, "
                "or unbound PersistentVolumeClaims (PVCs)."
            )

            investigation_steps = [
                f"Inspect scheduling events and conditions: kubectl describe pod {pod.name} -n {pod.namespace}",
                "Verify cluster-wide node allocatable resources against pod resource requests.",
                "Check PersistentVolumeClaim binding status if the pod mounts persistent storage.",
                "Review node taints, tolerations, and nodeSelector / affinity specifications.",
            ]

            uncertainties = [
                "Whether the scheduling block is due to quota exhaustion, volume provisioning, or node taints requires inspecting pod event reasons.",
            ]

            candidate = IncidentCandidate(
                cluster_id=context.cluster_id,
                resource_type="Pod",
                namespace=pod.namespace,
                resource_name=pod.name,
                rule_identifier=self.rule_identifier,
                severity=severity,
                title=f"Pod {pod.name} stuck in Pending phase ({elapsed_seconds}s)",
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

