# KubeWatch — Diagnostic and Detection Rules

This document specifies the deterministic, rule-based anomaly detection and diagnostic engine for KubeWatch.

In accordance with KubeWatch architectural principles, all detection rules evaluate live Kubernetes API state and verified Prometheus metrics. Rules never invent metric names or synthesize alert data.

---

## 1. Overview and Design Principles

1. **Separation of Concerns:**
   Rule logic lives under `backend/app/diagnostics/rules/`, fully decoupled from FastAPI routes (`app/api/routes/incidents.py`) and presentation components.
2. **Deterministic Evaluation:**
   Heuristics and deterministic thresholds are evaluated without non-deterministic AI or uncalibrated statistical models.
3. **Idempotent Persistence & Deduplication:**
   Every incident is fingerprinted using a deterministic UUIDv5 identity generated from `(cluster_id, namespace, resource_type, resource_name, rule_identifier)`. Repeated evaluations update `last_observed_at`, append new supporting evidence, and refresh descriptions without spawning duplicate incident records.
4. **Explicit Lifecycle Management:**
   Incidents transition between `active`, `acknowledged`, and `resolved`. When the triggering condition clears, the incident is auto-resolved with a recorded `resolution_time`. Temporary metrics outages (e.g. Prometheus unreachable) never trigger false auto-resolution.
5. **Separation of Facts from Inferences:**
   Observed facts (exact counts, exit codes, bytes) are separated from diagnostic interpretations and recommended next steps.

---

## 2. Specification of Detection Rules

### Rule 1: Increased Container Restart Activity (`container-restart-activity`)

* **Purpose:** Detect pods whose containers are crash-looping or repeatedly terminating.
* **Required Data Sources:**
  * Kubernetes API: `v1.Pod.status.container_statuses` (specifically `restart_count`, `ready`, and `state.waiting.reason` / `state.terminated.reason` / `state.terminated.exit_code`).
* **Evaluation Window:** Current cumulative restart count and container state during each evaluation cycle.
* **Trigger Conditions:**
  * Container `restart_count >= restart_threshold` (default: 5), OR
  * Container state contains `"CrashLoopBackOff"` or `"Error"` with `restart_count > 0`.
* **Default Thresholds:**
  * `restart_threshold`: 5 restarts (Warning).
  * `critical_restart_threshold`: 15 restarts, OR termination reason containing `OOMKilled` / exit code 137 (Critical).
* **Severity:** `warning` or `critical`.
* **Recovery Conditions:**
  * All containers in the pod reach `ready == True` in phase `Running` with no waiting error states, OR
  * The crashing pod is terminated and deleted/replaced by a healthy replacement pod in the cluster.
* **Correlation:**
  * If exit code is 137 or reason is `OOMKilled`, correlates with container memory limit breaches.
  * If the pod is owned by a Deployment, correlates with replica deficits in `DeploymentAvailabilityRule`.
* **Investigation Steps:**
  1. Inspect container termination logs: `kubectl logs <pod> -c <container> -n <namespace> --previous`
  2. Inspect exit code and lifecycle events: `kubectl describe pod <pod> -n <namespace>`
  3. Validate environment configuration, database credentials, and dependent services.
* **Uncertainties & Limitations:**
  * Application-internal stack traces cannot be extracted from Kubernetes metadata alone; previous container log inspection is required.

---

### Rule 2: Pods Remaining Pending (`pod-pending-duration`)

* **Purpose:** Detect pods that remain stuck in the `Pending` phase without being scheduled or initialized.
* **Required Data Sources:**
  * Kubernetes API: `v1.Pod.status.phase == "Pending"`, `v1.Pod.metadata.creation_timestamp`, `v1.Pod.spec.node_name`.
* **Evaluation Window:** Elapsed wall-clock time from pod `creation_timestamp` to current sweep timestamp.
* **Trigger Conditions:**
  * `pod.phase == "Pending"` AND `elapsed_seconds >= pending_threshold_seconds`.
* **Default Thresholds:**
  * `pending_threshold_seconds`: 300 seconds / 5 minutes (Warning).
  * `critical_pending_threshold_seconds`: 900 seconds / 15 minutes (Critical).
* **Severity:** `warning` or `critical`.
* **Recovery Conditions:**
  * Pod phase transitions to `Running` or `Succeeded`, OR
  * The pod is deleted from the cluster.
* **Correlation:**
  * Evaluates cluster-wide node status: if cluster nodes report `MemoryPressure`, `DiskPressure`, or `NotReady`, cites cluster capacity exhaustion as a correlated blocker.
* **Investigation Steps:**
  1. Inspect scheduling conditions and scheduler events: `kubectl describe pod <pod> -n <namespace>`
  2. Compare pod resource requests against node allocatable CPU and memory: `kubectl describe nodes`
  3. Check PersistentVolumeClaim binding status if persistent storage is mounted: `kubectl get pvc -n <namespace>`
  4. Verify node taints, tolerations, and `nodeSelector` / affinity constraints.
* **Uncertainties & Limitations:**
  * Differentiating cluster queue delay from namespace resource quota limits requires examining `kube-scheduler` audit events.

---

### Rule 3: Deployment Availability Deficit (`deployment-replicas-unavailable`)

* **Purpose:** Detect deployments where available replicas fall below the desired replica count.
* **Required Data Sources:**
  * Kubernetes API: `v1.Deployment.spec.replicas`, `v1.Deployment.status.available_replicas`, `v1.Deployment.status.unavailable_replicas`, `v1.Deployment.status.conditions`.
* **Evaluation Window:** Instantaneous check during each sweep.
* **Trigger Conditions:**
  * `desired_replicas > 0` AND (`available_replicas < desired_replicas` OR `unavailable_replicas > 0`).
* **Default Thresholds:**
  * `min_unavailable_replicas`: 1.
* **Severity:**
  * `critical`: when `available_replicas == 0` (zero replicas available = complete service outage).
  * `warning`: when `available_replicas > 0` but less than `desired_replicas` (degraded capacity).
* **Recovery Conditions:**
  * `available_replicas >= desired_replicas` AND `unavailable_replicas == 0`, OR
  * The deployment is deleted from the cluster.
* **Correlation:**
  * Cross-references child pods in the deployment's namespace matching `<deployment_name>-*` that are restarting or failing readiness probes.
* **Investigation Steps:**
  1. Check deployment rollout status: `kubectl rollout status deployment/<deployment> -n <namespace>`
  2. Inspect child ReplicaSets and pods: `kubectl get pods -l app=<deployment> -n <namespace>`
  3. Review recent namespace warning events: `kubectl get events -n <namespace> --sort-by='.lastTimestamp'`
* **Uncertainties & Limitations:**
  * Active rolling deployments temporarily exhibit unavailable replicas during container image download; correlation with `Progressing` condition distinguishes active rollouts from persistent failures.

---

### Rule 4: High Memory Utilization Relative to Limit (`container-memory-high-utilization`)

* **Purpose:** Detect containers whose active memory working set nears their configured cgroup memory limit, threatening kernel OOM termination.
* **Required Data Sources:**
  * Kubernetes API: `v1.Pod.spec.containers[*].resources.limits.memory` (parsed to integer bytes).
  * Prometheus: `container_memory_working_set_bytes{namespace=~"...", pod=~"...", container!=""}` (instant query).
* **Evaluation Window:** Instantaneous working set reading from Prometheus instant query during each sweep.
* **Trigger Conditions:**
  * Container has a configured memory limit > 0, AND
  * Measured working set is available, AND
  * `(working_set_bytes / memory_limit_bytes) * 100 >= memory_threshold_percent`.
* **Default Thresholds:**
  * `memory_threshold_percent`: 85.0% (Warning).
  * `critical_memory_threshold_percent`: 95.0% (Critical — imminent risk of kernel OOMKill).
  * `recovery_threshold_percent`: 80.0% (Hysteresis threshold to prevent alerting chatter).
* **Severity:** `warning` or `critical`.
* **Recovery Conditions:**
  * Measured utilization drops below 80.0%, OR
  * Container memory limit is increased in the workload manifest, OR
  * The pod is deleted/replaced.
* **Missing Data Guard:**
  * If Prometheus is unreachable or returns empty data for a container, this rule skips evaluation without error and **never** auto-resolves existing incidents.
* **Correlation:**
  * Correlates with historical container exit codes: if container state indicates prior `OOMKilled` (exit code 137), cites recurring memory limit exhaustion.
* **Investigation Steps:**
  1. Inspect container live memory consumption: `kubectl top pod <pod> -n <namespace> --containers`
  2. Review application heap dumps, memory profilers, or caching growth patterns.
  3. Increase memory limit in the pod specification or apply KubeWatch right-sizing recommendations.
* **Uncertainties & Limitations:**
  * Linux cgroup `working_set` includes mapped files and active page cache; kernel reclaim may recover memory prior to hard OOM depending on page dirty rates.

---

### Rule 5: Kubernetes Node Pressure Conditions (`node-pressure-condition`)

* **Purpose:** Detect nodes experiencing resource pressure (`MemoryPressure`, `DiskPressure`, `PIDPressure`) or `NotReady` status.
* **Required Data Sources:**
  * Kubernetes API: `v1.Node.status.conditions` (`Ready`, `MemoryPressure`, `DiskPressure`, `PIDPressure`).
* **Evaluation Window:** Instantaneous check during each sweep.
* **Trigger Conditions:**
  * Any condition `MemoryPressure`, `DiskPressure`, or `PIDPressure` has `status == "True"`, OR
  * Condition `Ready` has `status != "True"`.
* **Default Thresholds:**
  * Condition assertion status `"True"` for pressure flags; `"False"` / `"Unknown"` for Ready.
* **Severity:**
  * `critical`: `MemoryPressure == "True"` OR `Ready != "True"`.
  * `warning`: `DiskPressure == "True"` OR `PIDPressure == "True"`.
* **Recovery Conditions:**
  * All pressure conditions return to `status == "False"` AND `Ready` status is `"True"`.
* **Correlation:**
  * Cites pods scheduled on the pressured node that face eviction risk.
* **Investigation Steps:**
  1. Inspect node conditions and kubelet event stream: `kubectl describe node <node>`
  2. Check node hardware utilization: `kubectl top node <node>`
  3. Check host disk usage and root filesystem capacity: `df -h`
  4. Review host kubelet daemon logs: `journalctl -u kubelet -e`
* **Uncertainties & Limitations:**
  * Differentiating transient disk pressure (e.g. temporary build artifact) from persistent storage exhaustion requires observing trend velocity.

---

## 3. Normalized Evidence Schema

Every generated incident records supporting evidence in the `incident_evidence` table matching the normalized structure:

```json
{
  "source_type": "kubernetes_api",
  "affected_resource": {
    "cluster_id": "default",
    "namespace": "production",
    "resource_type": "Pod",
    "resource_name": "payment-api",
    "container_name": "app"
  },
  "measured_value": {
    "restart_count": 8,
    "ready": false,
    "state": "waiting: CrashLoopBackOff"
  },
  "relevant_configuration": {
    "restart_threshold": 5,
    "critical_restart_threshold": 15
  },
  "explanation": "Restart count 8 meets or exceeds configured threshold 5 or indicates crash looping."
}
```

---

## 4. Background Polling and Scheduling

### Execution Architecture
* Configured by `POLL_INTERVAL_SECONDS` (default: 60s).
* Background tasks are executed by `DiagnosticsScheduler` (`backend/app/diagnostics/scheduler.py`).
* Synchronous Kubernetes client calls (`list_nodes`, `list_pods`, `list_deployments`) are offloaded using `asyncio.to_thread` to ensure the FastAPI event loop is never blocked.
* Overlapping sweeps are strictly prevented via `asyncio.Lock`.
* Clean shutdown is guaranteed via FastAPI `lifespan`: the scheduler cancels pending sleeps and awaits active sweep completion before process exit.

### Multi-Worker Limitations
In a single-process development setup (e.g. `uvicorn --workers 1`), `DiagnosticsScheduler` runs safely in-process.

**Important Note for Multi-Worker Environments:**
If Uvicorn is executed with multiple worker processes (e.g. `--workers 4`), each worker process spawns its own independent in-process scheduler, causing redundant, concurrent database sweeps. In multi-worker or multi-replica production deployments, one of the following architectural patterns should be used:
1. **Dedicated Scheduler Process:** Run a single dedicated worker container with `DiagnosticsScheduler`, while API worker containers handle REST requests with the scheduler disabled.
2. **Kubernetes Leader Election:** Use the Kubernetes Lease API (`coordination.k8s.io/v1`) so only one active pod performs sweeps at any time.
3. **Distributed Task Queue:** Offload sweeps to Celery or Arq backed by Redis.

