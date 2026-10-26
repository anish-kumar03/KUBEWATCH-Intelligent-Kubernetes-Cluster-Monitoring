"""Kubernetes service — read-only access to the Kubernetes API.

This module wraps the ``kubernetes`` Python client to provide typed
data to the rest of the application.  It performs **no write
operations** and **never retrieves Secret contents**.

Connection mode
---------------
The ``KUBERNETES_MODE`` setting controls how the client authenticates:

* ``local``  – loads ``~/.kube/config`` (optionally a specific context).
* ``in_cluster`` – uses the mounted ServiceAccount token.

If the chosen mode fails to initialise the client raises
``KubernetesConnectionError`` immediately rather than silently
falling back to the other mode.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

from app.core.config import KubernetesMode, Settings
from app.schemas.models import (
    ClusterOverview,
    ContainerInfo,
    ContainerResources,
    DeploymentCondition,
    DeploymentInfo,
    NodeCondition,
    NodeInfo,
    NodeResources,
    PodInfo,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class KubernetesConnectionError(Exception):
    """Raised when the Kubernetes API is unreachable or the selected
    connection mode fails to initialise."""


class KubernetesApiError(Exception):
    """Raised when a Kubernetes API call fails."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class KubernetesService:
    """Read-only facade over the Kubernetes Python client."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._core_v1: Optional[k8s_client.CoreV1Api] = None
        self._apps_v1: Optional[k8s_client.AppsV1Api] = None

    # -- lifecycle -----------------------------------------------------------

    def connect(self) -> None:
        """Initialise the Kubernetes client according to ``KUBERNETES_MODE``.

        Raises ``KubernetesConnectionError`` on failure — never falls
        back silently.
        """
        mode = self._settings.kubernetes_mode

        try:
            if mode == KubernetesMode.LOCAL:
                k8s_config.load_kube_config(
                    context=self._settings.kube_context,
                )
                logger.info(
                    "Kubernetes client initialised in LOCAL mode "
                    "(context=%s)",
                    self._settings.kube_context or "<current>",
                )

            elif mode == KubernetesMode.IN_CLUSTER:
                k8s_config.load_incluster_config()
                logger.info(
                    "Kubernetes client initialised in IN_CLUSTER mode"
                )

            else:
                raise KubernetesConnectionError(
                    f"Unknown KUBERNETES_MODE: {mode!r}"
                )
        except Exception as exc:
            raise KubernetesConnectionError(
                f"Failed to initialise Kubernetes client in "
                f"{mode.value!r} mode: {exc}"
            ) from exc

        self._core_v1 = k8s_client.CoreV1Api()
        self._apps_v1 = k8s_client.AppsV1Api()

    # -- guards --------------------------------------------------------------

    def _ensure_connected(self) -> None:
        if self._core_v1 is None or self._apps_v1 is None:
            raise KubernetesConnectionError(
                "Kubernetes client is not connected. Call connect() first."
            )

    # -- node helpers --------------------------------------------------------

    @staticmethod
    def _parse_node(node: k8s_client.V1Node) -> NodeInfo:
        """Convert a V1Node to our typed schema."""
        status = "Unknown"
        conditions: list[NodeCondition] = []

        if node.status and node.status.conditions:
            for cond in node.status.conditions:
                conditions.append(
                    NodeCondition(
                        type=cond.type,
                        status=cond.status,
                        reason=cond.reason,
                        message=cond.message,
                    )
                )
                if cond.type == "Ready":
                    status = "Ready" if cond.status == "True" else "NotReady"

        # Extract roles from labels
        roles: list[str] = []
        labels = (node.metadata.labels or {}) if node.metadata else {}
        for label_key in labels:
            if label_key.startswith("node-role.kubernetes.io/"):
                role = label_key.split("/", 1)[1]
                if role:
                    roles.append(role)

        capacity = NodeResources()
        allocatable = NodeResources()

        if node.status:
            if node.status.capacity:
                capacity = NodeResources(
                    cpu=node.status.capacity.get("cpu"),
                    memory=node.status.capacity.get("memory"),
                )
            if node.status.allocatable:
                allocatable = NodeResources(
                    cpu=node.status.allocatable.get("cpu"),
                    memory=node.status.allocatable.get("memory"),
                )

        created_at = None
        if node.metadata and node.metadata.creation_timestamp:
            created_at = node.metadata.creation_timestamp

        return NodeInfo(
            name=node.metadata.name if node.metadata else "unknown",
            status=status,
            roles=roles,
            capacity=capacity,
            allocatable=allocatable,
            conditions=conditions,
            created_at=created_at,
        )

    # -- pod helpers ---------------------------------------------------------

    @staticmethod
    def _parse_pod(pod: k8s_client.V1Pod) -> PodInfo:
        """Convert a V1Pod to our typed schema."""
        metadata = pod.metadata
        status_obj = pod.status
        spec = pod.spec

        phase = "Unknown"
        if status_obj and status_obj.phase:
            phase = status_obj.phase

        total_restarts = 0
        containers: list[ContainerInfo] = []

        # Map container specs by name for resource requests/limits
        spec_map: dict[str, k8s_client.V1Container] = {}
        if spec and spec.containers:
            for c in spec.containers:
                spec_map[c.name] = c

        if status_obj and status_obj.container_statuses:
            for cs in status_obj.container_statuses:
                total_restarts += cs.restart_count or 0

                # Determine current state string
                state_str = None
                if cs.state:
                    if cs.state.running:
                        state_str = "running"
                    elif cs.state.waiting:
                        state_str = f"waiting: {cs.state.waiting.reason or 'unknown'}"
                    elif cs.state.terminated:
                        state_str = (
                            f"terminated: {cs.state.terminated.reason or 'unknown'}"
                        )

                # Resource info from spec
                resources = ContainerResources()
                c_spec = spec_map.get(cs.name)
                if c_spec and c_spec.resources:
                    req = c_spec.resources.requests or {}
                    lim = c_spec.resources.limits or {}
                    resources = ContainerResources(
                        cpu_request=req.get("cpu"),
                        cpu_limit=lim.get("cpu"),
                        memory_request=req.get("memory"),
                        memory_limit=lim.get("memory"),
                    )

                containers.append(
                    ContainerInfo(
                        name=cs.name,
                        image=cs.image or "",
                        ready=cs.ready or False,
                        restart_count=cs.restart_count or 0,
                        state=state_str,
                        resources=resources,
                    )
                )

        created_at = None
        if metadata and metadata.creation_timestamp:
            created_at = metadata.creation_timestamp

        return PodInfo(
            name=metadata.name if metadata else "unknown",
            namespace=metadata.namespace if metadata else "default",
            phase=phase,
            node_name=spec.node_name if spec else None,
            restart_count=total_restarts,
            containers=containers,
            created_at=created_at,
        )

    # -- deployment helpers --------------------------------------------------

    @staticmethod
    def _parse_deployment(deploy: k8s_client.V1Deployment) -> DeploymentInfo:
        """Convert a V1Deployment to our typed schema."""
        metadata = deploy.metadata
        spec = deploy.spec
        status_obj = deploy.status

        conditions: list[DeploymentCondition] = []
        if status_obj and status_obj.conditions:
            for cond in status_obj.conditions:
                conditions.append(
                    DeploymentCondition(
                        type=cond.type,
                        status=cond.status,
                        reason=cond.reason,
                        message=cond.message,
                    )
                )

        strategy = None
        if spec and spec.strategy and spec.strategy.type:
            strategy = spec.strategy.type

        created_at = None
        if metadata and metadata.creation_timestamp:
            created_at = metadata.creation_timestamp

        return DeploymentInfo(
            name=metadata.name if metadata else "unknown",
            namespace=metadata.namespace if metadata else "default",
            replicas=spec.replicas if spec and spec.replicas is not None else 0,
            ready_replicas=(
                status_obj.ready_replicas
                if status_obj and status_obj.ready_replicas is not None
                else 0
            ),
            available_replicas=(
                status_obj.available_replicas
                if status_obj and status_obj.available_replicas is not None
                else 0
            ),
            unavailable_replicas=(
                status_obj.unavailable_replicas
                if status_obj and status_obj.unavailable_replicas is not None
                else 0
            ),
            strategy=strategy,
            conditions=conditions,
            created_at=created_at,
        )

    # -- public API ----------------------------------------------------------

    def list_nodes(self) -> List[NodeInfo]:
        """List all cluster nodes (read-only)."""
        self._ensure_connected()
        try:
            result = self._core_v1.list_node()  # type: ignore[union-attr]
            return [self._parse_node(n) for n in result.items]
        except ApiException as exc:
            raise KubernetesApiError(
                f"Failed to list nodes: {exc.reason}"
            ) from exc

    def list_pods(self, namespace: Optional[str] = None) -> List[PodInfo]:
        """List pods, optionally filtered by namespace (read-only)."""
        self._ensure_connected()
        try:
            if namespace:
                result = self._core_v1.list_namespaced_pod(  # type: ignore[union-attr]
                    namespace=namespace,
                )
            else:
                result = self._core_v1.list_pod_for_all_namespaces()  # type: ignore[union-attr]
            return [self._parse_pod(p) for p in result.items]
        except ApiException as exc:
            raise KubernetesApiError(
                f"Failed to list pods: {exc.reason}"
            ) from exc

    def list_deployments(
        self, namespace: Optional[str] = None
    ) -> List[DeploymentInfo]:
        """List deployments, optionally filtered by namespace (read-only)."""
        self._ensure_connected()
        try:
            if namespace:
                result = self._apps_v1.list_namespaced_deployment(  # type: ignore[union-attr]
                    namespace=namespace,
                )
            else:
                result = (
                    self._apps_v1.list_deployment_for_all_namespaces()  # type: ignore[union-attr]
                )
            return [self._parse_deployment(d) for d in result.items]
        except ApiException as exc:
            raise KubernetesApiError(
                f"Failed to list deployments: {exc.reason}"
            ) from exc

    def list_namespaces(self) -> List[str]:
        """Return a list of namespace names (read-only)."""
        self._ensure_connected()
        try:
            result = self._core_v1.list_namespace()  # type: ignore[union-attr]
            return [
                ns.metadata.name
                for ns in result.items
                if ns.metadata and ns.metadata.name
            ]
        except ApiException as exc:
            raise KubernetesApiError(
                f"Failed to list namespaces: {exc.reason}"
            ) from exc

    def get_cluster_overview(self) -> ClusterOverview:
        """Build an aggregated cluster overview (read-only).

        Aggregates node count, pod count, namespace count, deployment
        count, and total CPU/memory capacity.  Utilisation percentages
        require Prometheus and are left as ``None`` here.
        """
        nodes = self.list_nodes()
        pods = self.list_pods()
        namespaces = self.list_namespaces()
        deployments = self.list_deployments()

        # Aggregate capacity (simple sum of all node capacities)
        total_cpu_millicores = 0
        total_memory_bytes = 0
        for node in nodes:
            total_cpu_millicores += _parse_cpu(node.capacity.cpu)
            total_memory_bytes += _parse_memory(node.capacity.memory)

        return ClusterOverview(
            node_count=len(nodes),
            pod_count=len(pods),
            namespace_count=len(namespaces),
            deployment_count=len(deployments),
            cpu_capacity=f"{total_cpu_millicores}m",
            memory_capacity=f"{total_memory_bytes}",
            cpu_usage_percent=None,   # Prometheus needed
            memory_usage_percent=None,  # Prometheus needed
        )

    def check_health(self) -> bool:
        """Return ``True`` if the Kubernetes API is reachable."""
        self._ensure_connected()
        try:
            self._core_v1.get_api_resources()  # type: ignore[union-attr]
            return True
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Resource quantity helpers
# ---------------------------------------------------------------------------


def _parse_cpu(value: Optional[str]) -> int:
    """Parse a Kubernetes CPU quantity to millicores.

    Examples: ``"4"`` → 4000,  ``"500m"`` → 500,  ``"0.5"`` → 500.
    Returns 0 when the value is ``None`` or unparseable.
    """
    if not value:
        return 0
    try:
        if value.endswith("m"):
            return int(value[:-1])
        return int(float(value) * 1000)
    except (ValueError, TypeError):
        return 0


def _parse_memory(value: Optional[str]) -> int:
    """Parse a Kubernetes memory quantity to bytes.

    Supports suffixes: Ki, Mi, Gi, Ti, K, M, G, T, and plain integers.
    Returns 0 when the value is ``None`` or unparseable.
    """
    if not value:
        return 0

    suffixes = {
        "Ki": 1024,
        "Mi": 1024**2,
        "Gi": 1024**3,
        "Ti": 1024**4,
        "K": 1000,
        "M": 1000**2,
        "G": 1000**3,
        "T": 1000**4,
    }

    try:
        for suffix, multiplier in suffixes.items():
            if value.endswith(suffix):
                return int(float(value[: -len(suffix)]) * multiplier)
        return int(value)
    except (ValueError, TypeError):
        return 0
