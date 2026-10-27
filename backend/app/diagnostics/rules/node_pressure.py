"""Detection rule: Kubernetes node pressure and readiness conditions."""

from __future__ import annotations

from typing import List

from app.diagnostics.base import (
    DiagnosticRule,
    EvaluationContext,
    EvidenceData,
    IncidentCandidate,
)


class NodePressureRule(DiagnosticRule):
    """Detects Kubernetes nodes asserting pressure conditions (Memory, Disk, PID) or NotReady state."""

    rule_identifier = "node-pressure-condition"
    name = "Kubernetes Node Pressure Condition"
    description = (
        "Flags nodes reporting MemoryPressure, DiskPressure, PIDPressure, or NotReady status, "
        "which jeopardizes scheduled workloads and prevents new pod placements."
    )
    default_severity = "warning"
    default_thresholds = {}

    def evaluate(self, context: EvaluationContext) -> List[IncidentCandidate]:
        if not self.is_enabled(context):
            return []

        incidents: List[IncidentCandidate] = []

        for node in context.nodes:
            flagged_conditions = []
            is_critical = False

            # Check status and conditions
            if node.status.lower() != "ready":
                is_critical = True
                flagged_conditions.append({
                    "type": "Ready",
                    "status": node.status,
                    "reason": "NodeNotReady",
                    "message": f"Node status is {node.status}",
                })

            for cond in node.conditions:
                c_type = cond.type
                c_status = cond.status

                if c_type in ("MemoryPressure", "DiskPressure", "PIDPressure") and c_status == "True":
                    flagged_conditions.append({
                        "type": c_type,
                        "status": c_status,
                        "reason": cond.reason or "ConditionTrue",
                        "message": cond.message or "",
                    })
                    if c_type == "MemoryPressure":
                        is_critical = True

            if not flagged_conditions:
                continue

            severity = "critical" if is_critical else "warning"

            evidence_items = []
            condition_summaries = []

            for cond in flagged_conditions:
                condition_summaries.append(f"{cond['type']}={cond['status']} ({cond['reason']})")
                evidence_items.append(
                    EvidenceData(
                        evidence_type="node_condition",
                        summary=f"Node '{node.name}' asserted condition {cond['type']}={cond['status']} (reason: {cond['reason']}).",
                        observation_time=context.now,
                        source_type="kubernetes_api",
                        affected_resource={
                            "cluster_id": context.cluster_id,
                            "resource_type": "Node",
                            "resource_name": node.name,
                        },
                        measured_value={
                            "condition_type": cond["type"],
                            "status": cond["status"],
                            "reason": cond["reason"],
                            "message": cond["message"],
                            "node_roles": node.roles,
                        },
                        relevant_configuration={
                            "node_capacity_cpu": node.capacity.cpu,
                            "node_capacity_memory": node.capacity.memory,
                            "node_allocatable_cpu": node.allocatable.cpu,
                            "node_allocatable_memory": node.allocatable.memory,
                        },
                        explanation=(
                            f"Node asserted {cond['type']}={cond['status']}. The kubelet actively rejects "
                            f"new pods and may evict lower-priority BestEffort/Burstable pods when under pressure."
                        ),
                    )
                )

            # Correlate with pods assigned to this node
            assigned_pods = [p for p in context.pods if p.node_name == node.name]
            if assigned_pods:
                pod_names = [f"{p.namespace}/{p.name}" for p in assigned_pods[:5]]
                evidence_items.append(
                    EvidenceData(
                        evidence_type="pod_condition",
                        summary=(
                            f"Correlated workloads: {len(assigned_pods)} pod(s) are assigned to this node "
                            f"(sample: {', '.join(pod_names)})."
                        ),
                        observation_time=context.now,
                        source_type="kubernetes_api",
                        affected_resource={
                            "cluster_id": context.cluster_id,
                            "resource_type": "Node",
                            "resource_name": node.name,
                        },
                        measured_value={
                            "assigned_pod_count": len(assigned_pods),
                            "sample_assigned_pods": pod_names,
                        },
                        relevant_configuration={},
                        explanation="Pods running on this pressured node face risk of eviction or performance throttling.",
                    )
                )

            cond_str = ", ".join(condition_summaries)
            what_observed = (
                f"Node '{node.name}' reported abnormal condition(s): {cond_str}. "
                f"Node status is '{node.status}'."
            )
            why_flagged = (
                f"Node conditions indicate host-level distress: {cond_str}. "
                "Node pressure causes the kubelet to initiate pod evictions and reject new pod placements, "
                "threatening overall cluster capacity."
            )

            investigation_steps = [
                f"Inspect node events and detailed condition reasons: kubectl describe node {node.name}",
                f"Check node resource consumption: kubectl top node {node.name}",
                "Review kubelet and system logs on the host: journalctl -u kubelet -e",
                f"If hardware or disk capacity is failing, cordon the node to prevent scheduling: kubectl cordon {node.name}",
            ]

            uncertainties = [
                "Whether disk pressure is caused by container image cache, ephemeral volumes, or host log rotation requires filesystem inspection.",
            ]

            candidate = IncidentCandidate(
                cluster_id=context.cluster_id,
                resource_type="Node",
                namespace=None,  # Nodes are cluster-scoped
                resource_name=node.name,
                rule_identifier=self.rule_identifier,
                severity=severity,
                title=f"Node {node.name} under pressure ({cond_str})",
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

