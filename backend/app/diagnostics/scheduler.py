"""Background diagnostics scheduler for periodic cluster evaluation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from app.core.config import Settings
from app.db.session import session_scope
from app.diagnostics.base import EvaluationContext, utc_now
from app.diagnostics.engine import DiagnosticsEngine
from app.services.kubernetes_service import KubernetesService
from app.services.prometheus_service import PrometheusService

logger = logging.getLogger(__name__)


class DiagnosticsScheduler:
    """Manages periodic execution of the diagnostic engine in the background.

    Runs asynchronous and thread-offloaded evaluations without blocking
    the FastAPI event loop. Prevents overlapping sweeps via an internal lock.
    """

    def __init__(
        self,
        settings: Settings,
        k8s_service: KubernetesService,
        prom_service: PrometheusService,
        engine: Optional[DiagnosticsEngine] = None,
    ) -> None:
        self._settings = settings
        self._k8s_service = k8s_service
        self._prom_service = prom_service
        self._engine = engine or DiagnosticsEngine(settings)

        self._interval = settings.poll_interval_seconds
        self._scan_lock = asyncio.Lock()
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        """Return True if background scheduler task is currently active."""
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the background scheduler task."""
        if self.is_running:
            logger.warning("DiagnosticsScheduler is already running.")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name="kubewatch-diagnostics-scheduler")
        logger.info(
            "Diagnostics scheduler started with %ds scan interval.",
            self._interval,
        )

    async def stop(self) -> None:
        """Signal the scheduler to stop and await clean termination."""
        if not self.is_running:
            return

        logger.info("Stopping diagnostics scheduler...")
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Diagnostics scheduler stopped cleanly.")

    async def run_single_sweep(self) -> Dict[str, Any]:
        """Execute a single diagnostic sweep.
        
        Guarded against concurrent execution via asyncio.Lock.
        """
        if self._scan_lock.locked():
            logger.warning("Diagnostics sweep already in progress; skipping.")
            return {"status": "skipped", "reason": "scan_in_progress"}

        async with self._scan_lock:
            return await self._execute_sweep()

    async def _execute_sweep(self) -> Dict[str, Any]:
        """Collect cluster state, execute rules, and persist results."""
        unavailable_sources = set()

        # 1. Fetch Kubernetes state in thread pool to avoid blocking async loop
        try:
            nodes = await asyncio.to_thread(self._k8s_service.list_nodes)
            pods = await asyncio.to_thread(self._k8s_service.list_pods)
            deployments = await asyncio.to_thread(self._k8s_service.list_deployments)
        except Exception as exc:
            logger.error("Kubernetes state collection failed during sweep: %s", exc)
            return {"status": "error", "source": "kubernetes", "error": str(exc)}

        # 2. Fetch Prometheus memory telemetry
        pod_memory_bytes: Dict[Tuple[str, str], float] = {}
        container_memory_bytes: Dict[Tuple[str, str, str], float] = {}

        try:
            metrics_res = await self._prom_service.instant_query("pod_memory_usage_bytes")
            if metrics_res.error:
                logger.warning("Prometheus memory query returned error: %s", metrics_res.error)
                unavailable_sources.add("prometheus")
            else:
                for s in metrics_res.series:
                    labels = s.metric_labels
                    ns = labels.get("namespace")
                    pod = labels.get("pod")
                    container = labels.get("container")
                    if s.values and ns and pod:
                        val = s.values[-1].value
                        pod_memory_bytes[(ns, pod)] = val
                        if container:
                            container_memory_bytes[(ns, pod, container)] = val
        except Exception as exc:
            logger.warning("Prometheus telemetry unreachable during sweep: %s", exc)
            unavailable_sources.add("prometheus")

        # 3. Build evaluation context
        context = EvaluationContext(
            cluster_id=self._settings.app_env,
            nodes=nodes,
            pods=pods,
            deployments=deployments,
            pod_memory_bytes=pod_memory_bytes,
            container_memory_bytes=container_memory_bytes,
            now=utc_now(),
            unavailable_sources=unavailable_sources,
        )

        # 4. Evaluate rules and persist in database transaction
        try:
            with session_scope() as session:
                context.rule_configs = self._engine.load_rule_configurations(session)
                candidates = self._engine.run_rules(context)
                summary = self._engine.persist_evaluation(session, context, candidates)

            logger.info(
                "Diagnostics sweep complete: %d candidate(s), %d new, %d updated, %d resolved.",
                summary["flagged_candidates"],
                summary["persisted_new"],
                summary["updated_existing"],
                summary["auto_resolved"],
            )
            return {"status": "ok", "summary": summary}
        except Exception as exc:
            logger.error("Failed to persist diagnostic sweep: %s", exc, exc_info=True)
            return {"status": "error", "source": "database", "error": str(exc)}

    async def _run_loop(self) -> None:
        """Continuous execution loop with clean shutdown support."""
        try:
            # Run initial sweep immediately after startup
            await self.run_single_sweep()

            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(),
                        timeout=self._interval,
                    )
                    break  # Stop event was set
                except asyncio.TimeoutError:
                    # Interval elapsed; perform next sweep
                    await self.run_single_sweep()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Unhandled error in diagnostics loop: %s", exc, exc_info=True)

