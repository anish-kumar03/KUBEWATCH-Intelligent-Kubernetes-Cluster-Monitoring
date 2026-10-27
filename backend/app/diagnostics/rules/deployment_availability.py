"""Detection rule: Deployments with fewer available replicas than desired."""

from __future__ import annotations

from typing import List

from app.diagnostics.base import (
    DiagnosticRule,
    EvaluationContext,
    EvidenceData,
    IncidentCandidate,
)


class DeploymentAvailabilityRule(DiagnosticRule):
    """Detects deployments experiencing replica deficits or unavailable replicas."""

    rule_identifier = "deployment-replicas-unavailable"
    name = "Deployment Replica Availability Deficit"
    description = (
        "Flags deployments where available replica count is less than desired replicas, "
        "indicating rollout failures, crashing pods, or insufficient cluster capacity."
    )
    default_severity = "warning"
    default_thresholds = {
        "min_unavailable_replicas": 1,
    }

    def evaluate(self, context: EvaluationContext) -> List[IncidentCandidate]:
        if not self.is_enabled(context):
            return []

        incidents: List[IncidentCandidate] = []

        for deploy in context.deployments:
            desired = deploy.replicas
            available = deploy.available_replicas
            unavailable = deploy.unavailable_replicas
            ready = deploy.ready_replicas

            # Only evaluate workloads expecting running replicas
            if desired <= 0:
                continue

            deficit = max(0, desired - available)
            if deficit <= 0 and unavailable <= 0:
                continue

            # Complete outage vs partial degradation
            severity = "critical" if available == 0 else "warning"

            evidence_items = [
                EvidenceData(
                    evidence_type="replica_deficit",
                    summary=(
                        f"Deployment '{deploy.name}' has {available}/{desired} available replicas "
                        f"({unavailable} reported unavailable, deficit: {deficit})."
                    ),
                    observation_time=context.now,
                    source_type="kubernetes_api",
                    affected_resource={
                        "cluster_id": context.cluster_id,
                        "namespace": deploy.namespace,
                        "resource_type": "Deployment",
                        "resource_name": deploy.name,
                    },
                    measured_value={
                        "desired_replicas": desired,
                        "available_replicas": available,
                        "ready_replicas": ready,
                        "unavailable_replicas": unavailable,
                        "deficit": deficit,
                        "strategy": deploy.strategy,
                    },
                    relevant_configuration={
                        "desired_replicas": desired,
                    },
                    explanation=(
                        f"Available replica count ({available}) is strictly below the desired specification "
                        f"({desired}), violating service capacity requirements."
                    ),
                )
            ]

            # Correlate with related pods in the same namespace
            failing_child_pods = [
                p for p in context.pods
                if p.namespace == deploy.namespace
                and p.name.startswith(f"{deploy.name}-")
                and (p.phase != "Running" or p.restart_count > 0)
            ]

            if failing_child_pods:
                failing_names = [f"{p.name} (phase={p.phase}, restarts={p.restart_count})" for p in failing_child_pods[:3]]
                evidence_items.append(
                    EvidenceData(
                        evidence_type="container_state",
                        summary=(
                            f"Correlated child pods failing readiness or restarting: {', '.join(failing_names)}."
                        ),
                        observation_time=context.now,
                        source_type="kubernetes_api",
                        affected_resource={
                            "cluster_id": context.cluster_id,
                            "namespace": deploy.namespace,
                            "resource_type": "Deployment",
                            "resource_name": deploy.name,
                        },
                        measured_value={
                            "failing_pod_count": len(failing_child_pods),
                            "sample_pods": [p.name for p in failing_child_pods[:3]],
                        },
                        relevant_configuration={},
                        explanation="Underlying child pods are either not in Running phase or restarting repeatedly.",
                    )
                )

            what_observed = (
                f"Deployment '{deploy.name}' in namespace '{deploy.namespace}' has {available} available replicas "
                f"out of {desired} desired ({unavailable} unavailable)."
            )
            why_flagged = (
                f"Replica deficit of {deficit} replica(s) detected. "
                + ("Zero replicas are currently serving traffic (complete outage). " if available == 0 else "Workload capacity is degraded. ")
                + "Deployments with unavailable replicas often point to container startup probe failures, CrashLoopBackOff, or resource quotas."
            )

            investigation_steps = [
                f"Check deployment rollout status: kubectl rollout status deployment/{deploy.name} -n {deploy.namespace}",
                f"List child pods and review pod states: kubectl get pods -l app={deploy.name} -n {deploy.namespace}",
                f"Inspect deployment conditions and recent events: kubectl describe deployment {deploy.name} -n {deploy.namespace}",
            ]

            uncertainties = [
                "If a rolling deployment is currently progressing, this deficit may resolve once replacement pods complete initialization.",
            ]

            candidate = IncidentCandidate(
                cluster_id=context.cluster_id,
                resource_type="Deployment",
                namespace=deploy.namespace,
                resource_name=deploy.name,
                rule_identifier=self.rule_identifier,
                severity=severity,
                title=f"Deployment {deploy.name} replica deficit ({available}/{desired} available)",
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

