"""KubeWatch FastAPI application entry point.

Creates the FastAPI app, wires up CORS, registers routers, and
manages the lifecycle of backend services (Kubernetes client,
Prometheus client).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import cluster, deployments, health, metrics, nodes, pods
from app.core.config import Settings, get_settings
from app.services.kubernetes_service import KubernetesService
from app.services.prometheus_service import PrometheusService

logger = logging.getLogger(__name__)


def _configure_logging(settings: Settings) -> None:
    """Set up structured logging at the configured level."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup / shutdown of backend services.

    On startup:
      1. Load configuration.
      2. Connect the Kubernetes client (fail-fast, no silent fallback).
      3. Start the Prometheus HTTPX client.

    On shutdown:
      1. Close the Prometheus HTTPX client.
    """
    settings = get_settings()
    _configure_logging(settings)

    # Store settings so routes can read query constraints, etc.
    if not hasattr(app.state, "settings") or app.state.settings is None:
        app.state.settings = settings

    # --- Kubernetes ---
    if not hasattr(app.state, "kubernetes_service") or app.state.kubernetes_service is None:
        k8s_service = KubernetesService(settings)
        k8s_service.connect()  # raises on failure
        app.state.kubernetes_service = k8s_service
        logger.info("Kubernetes service started")

    # --- Prometheus ---
    if not hasattr(app.state, "prometheus_service") or app.state.prometheus_service is None:
        prom_service = PrometheusService(settings)
        await prom_service.start()
        app.state.prometheus_service = prom_service
        logger.info("Prometheus service started")

    yield  # application runs

    # --- shutdown ---
    if hasattr(app.state, "prometheus_service") and app.state.prometheus_service:
        if hasattr(app.state.prometheus_service, "close"):
            await app.state.prometheus_service.close()
            logger.info("Prometheus service stopped")


def create_app(lifespan_handler=lifespan) -> FastAPI:
    """Application factory.

    Returns a fully configured FastAPI instance.  Tests can call
    this function with lifespan_handler=None to get a fresh app
    without startup side effects.
    """
    settings = get_settings()

    app = FastAPI(
        title="KubeWatch API",
        description=(
            "Intelligent Kubernetes cluster monitoring and "
            "performance analysis system."
        ),
        version="0.1.0",
        lifespan=lifespan_handler,
    )

    # --- CORS ---
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

    # --- Routers ---
    prefix = "/api"
    app.include_router(health.router, prefix=prefix, tags=["health"])
    app.include_router(cluster.router, prefix=prefix, tags=["cluster"])
    app.include_router(nodes.router, prefix=prefix, tags=["nodes"])
    app.include_router(pods.router, prefix=prefix, tags=["pods"])
    app.include_router(deployments.router, prefix=prefix, tags=["deployments"])
    app.include_router(metrics.router, prefix=prefix, tags=["metrics"])

    return app


# Module-level app instance used by ``uvicorn app.main:app``.
app = create_app()
