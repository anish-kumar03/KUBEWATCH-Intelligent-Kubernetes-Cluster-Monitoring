"""Resource recommendation SQLAlchemy model."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    DateTime,
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ResourceRecommendation(Base):
    """Represents an intelligent sizing or scaling recommendation for a Kubernetes workload.
    
    Includes current allocation, measured telemetry summaries, suggested changes,
    and review tracking.
    """

    __tablename__ = "resource_recommendations"

    # Stable unique ID
    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        doc="Stable UUID identifier for the recommendation",
    )

    # Cluster identity
    cluster_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="default",
        index=True,
        doc="Target cluster identifier",
    )

    # Affected workload identity
    namespace: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        doc="Kubernetes namespace of the affected workload",
    )
    workload_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        doc="Workload kind: Deployment, StatefulSet, DaemonSet, etc.",
    )
    workload_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Name of the affected workload",
    )
    container_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        doc="Target container name if recommendation applies to a specific container",
    )

    # Recommendation classification
    recommendation_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        doc="Type of recommendation: cpu_request, cpu_limit, memory_request, memory_limit, replica_count",
    )
    observation_window: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="7d",
        doc="Duration of historical observation window (e.g. 24h, 7d, 30d)",
    )

    # Summaries (not raw timeseries)
    current_configuration: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Summary of current workload configuration (e.g. requests, limits, replicas)",
    )
    measured_usage: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Summary of measured metrics over window (e.g. p95_cpu, p99_memory, max_memory)",
    )

    # Recommendation narrative
    recommendation_text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        doc="Human-readable rationale and suggested configuration change",
    )

    # Workflow review state
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        index=True,
        doc="Review status: pending, applied, dismissed",
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Creation timestamp",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        doc="Last updated timestamp",
    )

    __table_args__ = (
        # Workload lookups
        Index(
            "ix_recommendations_workload",
            "cluster_id",
            "namespace",
            "workload_type",
            "workload_name",
        ),
        # Review status and type filtering
        Index("ix_recommendations_status_type", "review_status", "recommendation_type"),
        # Creation time sorting
        Index("ix_recommendations_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<ResourceRecommendation(id={self.id!r}, "
            f"workload={self.workload_type}/{self.namespace}/{self.workload_name!r}, "
            f"type={self.recommendation_type!r}, status={self.review_status!r})>"
        )
