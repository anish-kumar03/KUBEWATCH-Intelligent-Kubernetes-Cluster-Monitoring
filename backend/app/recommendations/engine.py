"""Resource recommendation engine orchestrating Kubernetes workloads, Prometheus metrics, and persistence."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.recommendation import ResourceRecommendation
from app.recommendations.calculator import (
    MetricStatistics,
    RecommendationCandidate,
    WorkloadResourceSpec,
    calculate_metric_statistics,
    evaluate_cpu_underutilization,
    evaluate_high_memory_limit_utilization,
    evaluate_insufficient_historical_data,
    evaluate_memory_underutilization,
    utc_now,
)
from app.recommendations.config import RecommendationConfig
from app.schemas.models import DeploymentInfo, MetricsResult, PodInfo
from app.services.kubernetes_service import KubernetesService
from app.services.prometheus_service import PrometheusService

logger = logging.getLogger(__name__)


class RecommendationEngine:
    """Orchestrates resource recommendation evaluation, heuristics, and database persistence."""

    def __init__(
        self,
        settings: Settings,
        config: Optional[RecommendationConfig] = None,
        k8s_service: Optional[KubernetesService] = None,
        prom_service: Optional[PrometheusService] = None,
    ) -> None:
        self._settings = settings
        self.config = config or RecommendationConfig()
        self._k8s = k8s_service
        self._prom = prom_service

    # -----------------------------------------------------------------------
    # Core Heuristic Evaluation (Deterministic & Testable)
    # -----------------------------------------------------------------------

    def evaluate_container(
        self,
        cluster_id: str,
        namespace: str,
        workload_type: str,
        workload_name: str,
        spec: WorkloadResourceSpec,
        cpu_stats: MetricStatistics,
        mem_stats: MetricStatistics,
    ) -> List[RecommendationCandidate]:
        """Evaluate resource sizing recommendations for a single workload container."""
        candidates: List[RecommendationCandidate] = []

        # 1. CPU Evaluation
        if cpu_stats.is_sufficient:
            cpu_rec = evaluate_cpu_underutilization(
                cluster_id=cluster_id,
                namespace=namespace,
                workload_type=workload_type,
                workload_name=workload_name,
                spec=spec,
                cpu_stats=cpu_stats,
                config=self.config,
            )
            if cpu_rec:
                candidates.append(cpu_rec)
        else:
            # Telemetry insufficient: alert if workload has configured CPU requests
            if spec.cpu_request_millicores is not None and spec.cpu_request_millicores > 0:
                candidates.append(
                    evaluate_insufficient_historical_data(
                        cluster_id=cluster_id,
                        namespace=namespace,
                        workload_type=workload_type,
                        workload_name=workload_name,
                        spec=spec,
                        stats=cpu_stats,
                        metric_name="CPU",
                        config=self.config,
                    )
                )

        # 2. Memory Limit Risk (checked whenever samples exist and limit is configured)
        limit_rec = evaluate_high_memory_limit_utilization(
            cluster_id=cluster_id,
            namespace=namespace,
            workload_type=workload_type,
            workload_name=workload_name,
            spec=spec,
            mem_stats=mem_stats,
            config=self.config,
        )
        if limit_rec:
            candidates.append(limit_rec)

        # 3. Memory Underutilization & Insufficiency
        if mem_stats.is_sufficient:
            mem_rec = evaluate_memory_underutilization(
                cluster_id=cluster_id,
                namespace=namespace,
                workload_type=workload_type,
                workload_name=workload_name,
                spec=spec,
                mem_stats=mem_stats,
                config=self.config,
            )
            if mem_rec:
                candidates.append(mem_rec)
        else:
            # Telemetry insufficient: alert if memory requests/limits are configured (and not already alerting limit risk)
            has_mem_cfg = (
                (spec.memory_request_bytes is not None and spec.memory_request_bytes > 0)
                or (spec.memory_limit_bytes is not None and spec.memory_limit_bytes > 0)
            )
            if has_mem_cfg and not limit_rec:
                candidates.append(
                    evaluate_insufficient_historical_data(
                        cluster_id=cluster_id,
                        namespace=namespace,
                        workload_type=workload_type,
                        workload_name=workload_name,
                        spec=spec,
                        stats=mem_stats,
                        metric_name="Memory",
                        config=self.config,
                    )
                )

        return candidates

    def evaluate_workloads_from_data(
        self,
        deployments: List[DeploymentInfo],
        pods: List[PodInfo],
        cpu_metrics: MetricsResult,
        mem_metrics: MetricsResult,
        start_time: datetime,
        end_time: datetime,
        cluster_id: str = "default",
    ) -> List[RecommendationCandidate]:
        """Evaluate recommendations against explicitly provided workload models and Prometheus results.
        
        Extracts container resource specs from running pods and aggregates Prometheus
        container metrics per workload.
        """
        # Map Prometheus series by (namespace, pod_name, container_name)
        cpu_series_map: Dict[Tuple[str, str, str], List[float]] = {}
        for s in cpu_metrics.series:
            ns = s.metric_labels.get("namespace", "")
            p = s.metric_labels.get("pod", "")
            c = s.metric_labels.get("container", "")
            if ns and p and c:
                cpu_series_map[(ns, p, c)] = [dp.value for dp in s.values]

        mem_series_map: Dict[Tuple[str, str, str], List[float]] = {}
        for s in mem_metrics.series:
            ns = s.metric_labels.get("namespace", "")
            p = s.metric_labels.get("pod", "")
            c = s.metric_labels.get("container", "")
            if ns and p and c:
                mem_series_map[(ns, p, c)] = [dp.value for dp in s.values]

        # Group pods by namespace and deployment prefix
        pods_by_ns: Dict[str, List[PodInfo]] = defaultdict(list)
        for pod in pods:
            pods_by_ns[pod.namespace].append(pod)

        candidates: List[RecommendationCandidate] = []
        handled_pods: set[str] = set()

        # 1. Evaluate Deployments
        for dep in deployments:
            ns = dep.namespace
            matching_pods = [
                p for p in pods_by_ns[ns]
                if p.name.startswith(f"{dep.name}-")
            ]
            if not matching_pods:
                continue

            # Identify containers from the representative pod
            rep_pod = matching_pods[0]
            for container in rep_pod.containers:
                handled_pods.update(p.name for p in matching_pods)
                spec = WorkloadResourceSpec.from_container_resources(
                    container_name=container.name,
                    cpu_request=container.resources.cpu_request,
                    cpu_limit=container.resources.cpu_limit,
                    memory_request=container.resources.memory_request,
                    memory_limit=container.resources.memory_limit,
                )

                # Aggregate pod container points for this deployment container across replicas
                cpu_points = self._aggregate_container_points(matching_pods, container.name, cpu_series_map)
                mem_points = self._aggregate_container_points(matching_pods, container.name, mem_series_map)

                cpu_stats = calculate_metric_statistics(cpu_points, start_time, end_time, self.config)
                mem_stats = calculate_metric_statistics(mem_points, start_time, end_time, self.config)

                container_recs = self.evaluate_container(
                    cluster_id=cluster_id,
                    namespace=ns,
                    workload_type="Deployment",
                    workload_name=dep.name,
                    spec=spec,
                    cpu_stats=cpu_stats,
                    mem_stats=mem_stats,
                )
                candidates.extend(container_recs)

        # 2. Evaluate remaining standalone pods (e.g. StatefulSet or DaemonSet pods)
        for pod in pods:
            if pod.name in handled_pods:
                continue
            for container in pod.containers:
                spec = WorkloadResourceSpec.from_container_resources(
                    container_name=container.name,
                    cpu_request=container.resources.cpu_request,
                    cpu_limit=container.resources.cpu_limit,
                    memory_request=container.resources.memory_request,
                    memory_limit=container.resources.memory_limit,
                )

                cpu_points = cpu_series_map.get((pod.namespace, pod.name, container.name), [])
                mem_points = mem_series_map.get((pod.namespace, pod.name, container.name), [])

                cpu_stats = calculate_metric_statistics(cpu_points, start_time, end_time, self.config)
                mem_stats = calculate_metric_statistics(mem_points, start_time, end_time, self.config)

                container_recs = self.evaluate_container(
                    cluster_id=cluster_id,
                    namespace=pod.namespace,
                    workload_type="Pod",
                    workload_name=pod.name,
                    spec=spec,
                    cpu_stats=cpu_stats,
                    mem_stats=mem_stats,
                )
                candidates.extend(container_recs)

        return candidates

    def _aggregate_container_points(
        self,
        pods: List[PodInfo],
        container_name: str,
        series_map: Dict[Tuple[str, str, str], List[float]],
    ) -> List[float]:
        """Collect observed telemetry points across all replica pods for a container.
        
        Combines samples from all pods running the container image.
        """
        all_points: List[float] = []
        for pod in pods:
            pts = series_map.get((pod.namespace, pod.name, container_name), [])
            all_points.extend(pts)
        return all_points

    # -----------------------------------------------------------------------
    # Async Live Evaluation
    # -----------------------------------------------------------------------

    async def evaluate_live(
        self,
        cluster_id: str = "default",
    ) -> List[RecommendationCandidate]:
        """Fetch live workloads from Kubernetes and telemetry from Prometheus to generate candidates."""
        if not self._k8s or not self._prom:
            logger.warning("Kubernetes or Prometheus service not configured on engine; skipping live evaluation.")
            return []

        # Read workloads
        try:
            deployments = self._k8s.list_deployments()
            pods = self._k8s.list_pods()
        except Exception as exc:
            logger.error("Failed to list workloads from Kubernetes: %s", exc)
            return []

        # Query Prometheus metrics over historical window
        end_time = utc_now()
        start_time = end_time - timedelta(hours=self.config.observation_window_hours)

        try:
            cpu_res = await self._prom.range_query(
                "container_cpu_usage_cores",
                start=start_time,
                end=end_time,
                step_seconds=self.config.step_seconds,
            )
            mem_res = await self._prom.range_query(
                "container_memory_usage_bytes",
                start=start_time,
                end=end_time,
                step_seconds=self.config.step_seconds,
            )
        except Exception as exc:
            logger.error("Failed to fetch metric range from Prometheus: %s", exc)
            cpu_res = MetricsResult(query_name="container_cpu_usage_cores", error=str(exc))
            mem_res = MetricsResult(query_name="container_memory_usage_bytes", error=str(exc))

        return self.evaluate_workloads_from_data(
            deployments=deployments,
            pods=pods,
            cpu_metrics=cpu_res,
            mem_metrics=mem_res,
            start_time=start_time,
            end_time=end_time,
            cluster_id=cluster_id,
        )

    # -----------------------------------------------------------------------
    # Database Persistence & Review Lifecycle
    # -----------------------------------------------------------------------

    def persist_recommendations(
        self,
        session: Session,
        candidates: List[RecommendationCandidate],
    ) -> Dict[str, int]:
        """Persist recommendation candidates with deterministic fingerprinting and review tracking.
        
        - If recommendation is new: creates a record with review_status='pending'.
        - If recommendation already exists and is 'pending': updates telemetry and suggested changes.
        - If recommendation was already 'applied' or 'dismissed': preserves user review decision.
        
        Returns dict with counts of 'created', 'updated', and 'unchanged'.
        """
        created_count = 0
        updated_count = 0
        unchanged_count = 0
        now = utc_now()

        for cand in candidates:
            rec_id = cand.fingerprint
            rec = session.get(ResourceRecommendation, rec_id)

            if rec is None:
                rec = ResourceRecommendation(
                    id=rec_id,
                    cluster_id=cand.cluster_id,
                    namespace=cand.namespace,
                    workload_type=cand.workload_type,
                    workload_name=cand.workload_name,
                    container_name=cand.container_name,
                    recommendation_type=cand.recommendation_type,
                    observation_window=cand.observation_window,
                    current_configuration=cand.current_configuration,
                    measured_usage=cand.measured_usage,
                    recommendation_text=cand.recommendation_text,
                    review_status="pending",
                    created_at=now,
                    updated_at=now,
                )
                session.add(rec)
                created_count += 1
            elif rec.review_status == "pending":
                # Update pending recommendation with fresh observations
                rec.observation_window = cand.observation_window
                rec.current_configuration = cand.current_configuration
                rec.measured_usage = cand.measured_usage
                rec.recommendation_text = cand.recommendation_text
                rec.updated_at = now
                updated_count += 1
            else:
                # User already marked applied or dismissed; preserve state
                unchanged_count += 1

        session.commit()
        return {
            "created": created_count,
            "updated": updated_count,
            "unchanged": unchanged_count,
            "total_candidates": len(candidates),
        }

