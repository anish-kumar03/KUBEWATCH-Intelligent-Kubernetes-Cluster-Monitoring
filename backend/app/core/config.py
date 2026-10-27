"""Application configuration using Pydantic Settings.

All settings are read from environment variables with an optional .env file.
Defaults are tuned for local development against Minikube.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class KubernetesMode(str, Enum):
    """Kubernetes client connection mode.

    LOCAL  – load kubeconfig from the default file (~/.kube/config).
    IN_CLUSTER – use the Kubernetes in-cluster ServiceAccount token.

    The backend will NOT silently fall back between modes.
    If the selected mode fails to initialise, it raises immediately.
    """

    LOCAL = "local"
    IN_CLUSTER = "in_cluster"


class Settings(BaseSettings):
    """Central application settings.

    Environment variables are prefixed with KUBEWATCH_ for clarity,
    except where the user request specifies a bare name (e.g.
    KUBERNETES_MODE).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(
        default="development",
        description="Application environment (development, staging, production).",
    )

    poll_interval_seconds: int = Field(
        default=60,
        description="Polling interval in seconds for background metric and status collectors.",
    )

    # --- Kubernetes -----------------------------------------------------------

    kubernetes_mode: KubernetesMode = Field(
        default=KubernetesMode.LOCAL,
        description=(
            "How to connect to the Kubernetes API. "
            "'local' reads ~/.kube/config; "
            "'in_cluster' uses the mounted ServiceAccount token."
        ),
    )

    kube_context: str | None = Field(
        default=None,
        description=(
            "Kubernetes context name to use in LOCAL mode. "
            "None means the current-context in kubeconfig."
        ),
    )

    # --- Prometheus -----------------------------------------------------------

    prometheus_url: str = Field(
        default="http://localhost:9090",
        description="Prometheus base URL (HTTP API v1).",
    )

    prometheus_timeout_seconds: float = Field(
        default=10.0,
        description="HTTP timeout for Prometheus queries.",
    )

    # --- Database -------------------------------------------------------------

    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("database_url", "kubewatch_database_url"),
        description="Database connection URL (e.g. postgresql+psycopg://user:pass@host:port/db).",
    )

    # --- CORS -----------------------------------------------------------------

    cors_origins: List[str] | str = Field(
        default=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:5174",
        ],
        description="Allowed CORS origins for the frontend.",
    )

    @field_validator("cors_origins", mode="after")
    @classmethod
    def assemble_cors_origins(cls, v: Any) -> List[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                import json
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    # --- Logging --------------------------------------------------------------

    log_level: str = Field(
        default="INFO",
        description="Python logging level.",
    )

    # --- Query constraints ----------------------------------------------------

    max_query_range_hours: int = Field(
        default=168,  # 7 days
        description="Maximum allowed time-range for metric queries, in hours.",
    )

    metrics_step_seconds: int = Field(
        default=60,
        description="Default step/resolution for Prometheus range queries.",
    )


def get_settings() -> Settings:
    """Create and return a Settings instance.

    Each call reads environment variables afresh.  For production use,
    cache the result with ``functools.lru_cache`` at the call-site.
    """
    return Settings()
