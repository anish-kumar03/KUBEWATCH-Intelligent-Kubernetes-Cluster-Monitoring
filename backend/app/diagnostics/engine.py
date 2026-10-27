"""Diagnostics engine — orchestrates diagnostic rules, correlation, and persistence."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence, Set
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.diagnostics.base import (
    DiagnosticRule,
    EvaluationContext,
    IncidentCandidate,
)
from app.diagnostics.rules import ALL_RULES
from app.models.incident import Incident, IncidentEvidence
from app.models.rule import DetectionRule
from app.schemas.models import DeploymentInfo, NodeInfo, PodInfo

logger = logging.getLogger(__name__)


class DiagnosticsEngine:
    """Executes diagnostic rules, correlates findings, and manages incident persistence."""

    def __init__(
        self,
        settings: Settings,
        rules: Optional[Sequence[DiagnosticRule]] = None,
    ) -> None:
        self._settings = settings
        self._rules: List[DiagnosticRule] = list(rules if rules is not None else ALL_RULES)

    @property
    def rules(self) -> List[DiagnosticRule]:
        """Return the active diagnostic rules."""
        return self._rules

    def load_rule_configurations(self, session: Session) -> Dict[str, Dict[str, Any]]:
        """Load rule configuration overrides stored in PostgreSQL."""
        try:
            stmt = select(DetectionRule)
            db_rules = session.scalars(stmt).all()
            return {
                r.id: {
                    "enabled": r.enabled,
                    "severity": r.severity,
                    "threshold_config": r.threshold_config,
                }
                for r in db_rules
            }
        except Exception as exc:
            logger.warning("Could not load rule configs from database; using defaults: %s", exc)
            return {}

    def run_rules(self, context: EvaluationContext) -> List[IncidentCandidate]:
        """Evaluate all active diagnostic rules against the evaluation context."""
        candidates: List[IncidentCandidate] = []
        for rule in self._rules:
            try:
                rule_candidates = rule.evaluate(context)
                candidates.extend(rule_candidates)
            except Exception as exc:
                logger.error(
                    "Rule %r failed during evaluation: %s",
                    rule.rule_identifier,
                    exc,
                    exc_info=True,
                )
        return candidates

    def persist_evaluation(
        self,
        session: Session,
        context: EvaluationContext,
        candidates: List[IncidentCandidate],
    ) -> Dict[str, int]:
        """Persist candidates with deduplication, fingerprinting, and lifecycle auto-recovery.
        
        Returns count of new, updated, and resolved incidents.
        """
        now = context.now
        new_count = 0
        updated_count = 0
        resolved_count = 0

        # Map candidate fingerprints
        active_candidate_map: Dict[str, IncidentCandidate] = {
            c.fingerprint: c for c in candidates
        }

        # Query all existing open (active or acknowledged) incidents
        stmt = select(Incident).where(Incident.status.in_(["active", "acknowledged"]))
        open_incidents = session.scalars(stmt).all()
        open_incident_map: Dict[str, Incident] = {inc.id: inc for inc in open_incidents}

        # 1. Update existing or insert new incidents
        for fingerprint, candidate in active_candidate_map.items():
            existing = open_incident_map.get(fingerprint)
            if existing is not None:
                # Update existing incident
                existing.last_observed_at = now
                existing.severity = candidate.severity
                existing.title = candidate.title
                existing.description = candidate.description

                # Append new normalized evidence
                for ev in candidate.evidence:
                    evidence_record = IncidentEvidence(
                        incident_id=existing.id,
                        evidence_type=ev.evidence_type,
                        summary=ev.summary,
                        observation_time=ev.observation_time,
                        source_metadata=ev.to_source_metadata(),
                    )
                    session.add(evidence_record)
                updated_count += 1
            else:
                # Insert new incident with deterministic fingerprint as ID
                new_incident = Incident(
                    id=fingerprint,
                    cluster_id=candidate.cluster_id,
                    resource_type=candidate.resource_type,
                    namespace=candidate.namespace,
                    resource_name=candidate.resource_name,
                    rule_identifier=candidate.rule_identifier,
                    severity=candidate.severity,
                    title=candidate.title,
                    description=candidate.description,
                    first_observed_at=candidate.first_observed_at,
                    last_observed_at=candidate.last_observed_at,
                    status="active",
                    resolution_time=None,
                )
                session.add(new_incident)

                for ev in candidate.evidence:
                    evidence_record = IncidentEvidence(
                        incident_id=new_incident.id,
                        evidence_type=ev.evidence_type,
                        summary=ev.summary,
                        observation_time=ev.observation_time,
                        source_metadata=ev.to_source_metadata(),
                    )
                    session.add(evidence_record)
                new_count += 1

        # 2. Check for resolved incidents (recovery conditions)
        # Resources present in cluster state
        known_pod_keys = {(p.namespace, p.name) for p in context.pods}
        known_deploy_keys = {(d.namespace, d.name) for d in context.deployments}
        known_node_names = {n.name for n in context.nodes}

        for inc in open_incidents:
            if inc.id in active_candidate_map:
                # Still active
                continue

            # Check if this incident should be auto-resolved
            rule_id = inc.rule_identifier

            if rule_id == "container-memory-high-utilization":
                # Do NOT resolve if Prometheus was down or metrics missing
                if "prometheus" in context.unavailable_sources:
                    logger.debug("Skipping recovery check for %s: Prometheus unavailable", inc.id)
                    continue

                # Check if pod still exists
                pod_key = (inc.namespace or "default", inc.resource_name)
                if pod_key not in known_pod_keys:
                    # Pod was deleted
                    self._resolve_incident(inc, now, "Affected pod no longer exists in cluster.")
                    resolved_count += 1
                else:
                    # Memory was measured and is below warning threshold
                    self._resolve_incident(inc, now, "Memory utilization dropped below threshold.")
                    resolved_count += 1

            elif rule_id == "pod-pending-duration":
                pod_key = (inc.namespace or "default", inc.resource_name)
                matching_pod = next((p for p in context.pods if (p.namespace, p.name) == pod_key), None)
                if matching_pod is None:
                    self._resolve_incident(inc, now, "Pending pod was removed from cluster.")
                    resolved_count += 1
                elif matching_pod.phase.lower() in ("running", "succeeded"):
                    self._resolve_incident(inc, now, f"Pod transitioned to phase '{matching_pod.phase}'.")
                    resolved_count += 1

            elif rule_id == "container-restart-activity":
                pod_key = (inc.namespace or "default", inc.resource_name)
                matching_pod = next((p for p in context.pods if (p.namespace, p.name) == pod_key), None)
                if matching_pod is None:
                    self._resolve_incident(inc, now, "Pod was removed from cluster.")
                    resolved_count += 1
                elif matching_pod.phase.lower() == "running" and all(c.ready for c in matching_pod.containers):
                    self._resolve_incident(inc, now, "All containers are healthy and ready in Running phase.")
                    resolved_count += 1

            elif rule_id == "deployment-replicas-unavailable":
                deploy_key = (inc.namespace or "default", inc.resource_name)
                matching_deploy = next((d for d in context.deployments if (d.namespace, d.name) == deploy_key), None)
                if matching_deploy is None:
                    self._resolve_incident(inc, now, "Deployment was removed from cluster.")
                    resolved_count += 1
                elif (
                    matching_deploy.replicas > 0
                    and matching_deploy.available_replicas >= matching_deploy.replicas
                    and matching_deploy.unavailable_replicas == 0
                ):
                    self._resolve_incident(inc, now, "All desired deployment replicas are available and ready.")
                    resolved_count += 1

            elif rule_id == "node-pressure-condition":
                matching_node = next((n for n in context.nodes if n.name == inc.resource_name), None)
                if matching_node is None:
                    self._resolve_incident(inc, now, "Node was removed from cluster.")
                    resolved_count += 1
                elif (
                    matching_node.status == "Ready"
                    and not any(c.status == "True" for c in matching_node.conditions if "pressure" in c.type.lower())
                ):
                    self._resolve_incident(inc, now, "Node is Ready with all pressure conditions cleared.")
                    resolved_count += 1

        session.commit()

        return {
            "evaluated_rules": len(self._rules),
            "flagged_candidates": len(candidates),
            "persisted_new": new_count,
            "updated_existing": updated_count,
            "auto_resolved": resolved_count,
        }

    @staticmethod
    def _resolve_incident(incident: Incident, resolved_at: datetime, reason: str) -> None:
        """Helper to mark an incident as resolved."""
        incident.status = "resolved"
        incident.resolution_time = resolved_at
        incident.description = f"{incident.description}\n\n### Resolution\nAuto-resolved at {resolved_at.isoformat()}: {reason}"

