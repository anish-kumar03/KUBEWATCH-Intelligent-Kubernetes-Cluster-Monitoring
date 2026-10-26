"""Detection rule metadata and configuration SQLAlchemy model."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Index,
    JSON,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DetectionRule(Base):
    """Represents a configurable anomaly detection rule or rule metadata.
    
    Stores rule identification, human descriptions, severity classification,
    threshold parameters, and active status.
    """

    __tablename__ = "detection_rules"

    # Stable unique identifier (e.g., 'pod-crashlooping', 'node-memory-pressure')
    id: Mapped[str] = mapped_column(
        String(100),
        primary_key=True,
        doc="Unique rule identifier slug",
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        doc="Human-readable rule name",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        doc="Description of what this rule detects and when it triggers",
    )

    severity: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="warning",
        doc="Default severity when this rule fires: critical, warning, info",
    )

    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        index=True,
        doc="Whether this detection rule is actively evaluated",
    )

    threshold_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        doc="Dynamic threshold and evaluation parameters (e.g. cpu_percent, duration)",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Rule registration timestamp",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        doc="Last modification timestamp",
    )

    __table_args__ = (
        Index("ix_detection_rules_enabled_severity", "enabled", "severity"),
    )

    def __repr__(self) -> str:
        return (
            f"<DetectionRule(id={self.id!r}, name={self.name!r}, "
            f"severity={self.severity!r}, enabled={self.enabled!r})>"
        )
