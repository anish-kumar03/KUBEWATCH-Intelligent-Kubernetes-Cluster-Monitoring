"""Incident and incident evidence SQLAlchemy models."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Incident(Base):
    """Represents a detected operational incident in the Kubernetes cluster.
    
    Stores status history, affected resource identity, detection rule, and
    lifecycle timestamps.
    """

    __tablename__ = "incidents"

    # Stable unique ID
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Stable UUID identifier for the incident",
    )

    # Cluster identity
    cluster_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="default",
        index=True,
        doc="Target cluster identifier (e.g. minikube, prod-cluster)",
    )

    # Affected resource coordinates
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Resource kind (e.g. Pod, Deployment, Node)",
    )
    namespace: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        index=True,
        doc="Kubernetes namespace (null for cluster-scoped resources like Nodes)",
    )
    resource_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Name of the affected Kubernetes resource",
    )

    # Rule and classification
    rule_identifier: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Identifier of the detection rule that triggered this incident",
    )
    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="warning",
        doc="Severity level (e.g. critical, warning, info)",
    )

    # Human-readable content
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable title describing the incident",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Detailed explanation of the issue and potential impact",
    )

    # Lifecycle timestamps
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        doc="Timestamp when the condition was first observed",
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        doc="Timestamp when the condition was most recently observed",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True,
        doc="Current incident status: active, acknowledged, or resolved",
    )
    resolution_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
        doc="Timestamp when the incident transitioned to resolved",
    )

    # Auditing
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    evidence: Mapped[List[IncidentEvidence]] = relationship(
        "IncidentEvidence",
        back_populates="incident",
        cascade="all, delete-orphan",
        order_by="IncidentEvidence.observation_time.desc()",
        lazy="selectin",
    )

    __table_args__ = (
        # Fast query for deduplication and active state checks
        Index(
            "ix_incidents_workload_rule_status",
            "cluster_id",
            "namespace",
            "resource_type",
            "resource_name",
            "rule_identifier",
            "status",
        ),
        # Dashboard filtering by status and severity
        Index("ix_incidents_status_severity", "status", "severity"),
        # Chronological sorting
        Index("ix_incidents_last_observed_at", "last_observed_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Incident(id={self.id!r}, rule={self.rule_identifier!r}, "
            f"resource={self.resource_type}/{self.resource_name!r}, "
            f"status={self.status!r}, severity={self.severity!r})>"
        )


class IncidentEvidence(Base):
    """Represents a piece of supporting evidence for an incident.
    
    Includes metric breaches, Kubernetes events, logs, or state snapshots.
    """

    __tablename__ = "incident_evidence"

    # Stable unique ID
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Stable UUID identifier for the evidence entry",
    )

    # Incident reference
    incident_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("incidents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        doc="Foreign key reference to parent incident",
    )

    # Evidence details
    evidence_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Type of evidence: metric_breach, k8s_event, log_pattern, condition_change",
    )
    summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Human-readable summary of the observed evidence",
    )
    observation_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utc_now,
        doc="Timestamp when this specific evidence occurred",
    )

    # Arbitrary structured metadata (metric values, threshold, event reason, etc.)
    source_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Structured metadata such as raw values, threshold, event reason, etc.",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    incident: Mapped[Incident] = relationship(
        "Incident",
        back_populates="evidence",
    )

    __table_args__ = (
        Index("ix_incident_evidence_incident_time", "incident_id", "observation_time"),
    )

    def __repr__(self) -> str:
        return (
            f"<IncidentEvidence(id={self.id!r}, incident_id={self.incident_id!r}, "
            f"type={self.evidence_type!r}, observation_time={self.observation_time!r})>"
        )
