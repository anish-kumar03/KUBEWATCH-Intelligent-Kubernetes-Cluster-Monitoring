"""Health check endpoint.

Returns connectivity status for each backend dependency:
Kubernetes API and Prometheus.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas.models import ApiResponse, ComponentHealth, HealthData

router = APIRouter()


@router.get(
    "/health",
    response_model=ApiResponse[HealthData],
    summary="Backend health check",
    description=(
        "Reports connectivity status for every backend dependency. "
        "Returns HTTP 200 even if some components are unhealthy, so "
        "the response body can describe partial failures."
    ),
)
async def health_check(request: Request) -> ApiResponse[HealthData]:
    """Check connectivity to Kubernetes and Prometheus."""
    k8s_service = request.app.state.kubernetes_service
    prom_service = request.app.state.prometheus_service

    components: list[ComponentHealth] = []

    # --- Kubernetes ---
    try:
        k8s_ok = k8s_service.check_health()
        components.append(
            ComponentHealth(
                name="kubernetes",
                healthy=k8s_ok,
                message="Connected" if k8s_ok else "API unreachable",
            )
        )
    except Exception as exc:
        components.append(
            ComponentHealth(
                name="kubernetes",
                healthy=False,
                message=str(exc),
            )
        )

    # --- Prometheus ---
    try:
        prom_ok = await prom_service.check_health()
        components.append(
            ComponentHealth(
                name="prometheus",
                healthy=prom_ok,
                message="Connected" if prom_ok else "Unreachable",
            )
        )
    except Exception as exc:
        components.append(
            ComponentHealth(
                name="prometheus",
                healthy=False,
                message=str(exc),
            )
        )

    all_healthy = all(c.healthy for c in components)

    return ApiResponse(
        status="ok" if all_healthy else "degraded",
        data=HealthData(healthy=all_healthy, components=components),
    )
