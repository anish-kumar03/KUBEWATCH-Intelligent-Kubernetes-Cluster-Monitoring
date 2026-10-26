# KubeWatch — Requirements

## 1. Functional Requirements

### FR-1: Cluster Overview

| ID | Requirement |
|---|---|
| FR-1.1 | The system shall display total node count, pod count, and namespace count. |
| FR-1.2 | The system shall display cluster-wide CPU and memory utilization percentages. |
| FR-1.3 | The system shall display the count of active incidents and pending recommendations. |

### FR-2: Node Monitoring

| ID | Requirement |
|---|---|
| FR-2.1 | The system shall list all nodes with their status (Ready / NotReady). |
| FR-2.2 | The system shall display per-node CPU and memory capacity, allocatable resources, and current utilization. |
| FR-2.3 | The system shall display node conditions (DiskPressure, MemoryPressure, PIDPressure). |

### FR-3: Pod Monitoring

| ID | Requirement |
|---|---|
| FR-3.1 | The system shall list all pods filterable by namespace. |
| FR-3.2 | The system shall display per-pod phase (Running, Pending, Succeeded, Failed, Unknown). |
| FR-3.3 | The system shall display per-pod restart count, age, and container resource requests/limits. |
| FR-3.4 | The system shall display per-pod CPU and memory utilization from Prometheus. |

### FR-4: Deployment Monitoring

| ID | Requirement |
|---|---|
| FR-4.1 | The system shall list all deployments with desired, ready, available, and unavailable replica counts. |
| FR-4.2 | The system shall display deployment update strategy and last update timestamp. |

### FR-5: CPU and Memory Metrics

| ID | Requirement |
|---|---|
| FR-5.1 | The system shall retrieve CPU and memory usage metrics from Prometheus. |
| FR-5.2 | The system shall support time-range queries for historical metrics (up to 7 days). |
| FR-5.3 | The system shall present metrics as time-series charts. |
| FR-5.4 | Missing or unavailable metrics shall be displayed as "data unavailable" and not as zero. |

### FR-6: Restart Detection

| ID | Requirement |
|---|---|
| FR-6.1 | The system shall detect pods whose total restart count exceeds a configurable threshold. |
| FR-6.2 | Each restart incident shall include: pod name, namespace, container name, restart count, last termination reason, and last termination exit code. |

### FR-7: Pending-Pod Detection

| ID | Requirement |
|---|---|
| FR-7.1 | The system shall detect pods that remain in Pending phase. |
| FR-7.2 | Each pending-pod incident shall include: pod name, namespace, scheduling conditions, and relevant event messages. |

### FR-8: Deployment Availability Detection

| ID | Requirement |
|---|---|
| FR-8.1 | The system shall detect deployments with one or more unavailable replicas. |
| FR-8.2 | Each availability incident shall include: deployment name, namespace, desired vs. available replicas, and deployment conditions. |

### FR-9: Evidence-Backed Incidents

| ID | Requirement |
|---|---|
| FR-9.1 | Every detected incident shall be stored in PostgreSQL with a unique identifier, severity, detection timestamp, and structured evidence. |
| FR-9.2 | Evidence shall contain only observed facts; explanations shall be clearly distinguished from observations. |
| FR-9.3 | The API shall serve incidents sorted by severity and recency. |
| FR-9.4 | The frontend shall display incidents with their supporting evidence. |

### FR-10: Resource Recommendations

| ID | Requirement |
|---|---|
| FR-10.1 | The system shall compute CPU and memory right-sizing recommendations based on observed utilization. |
| FR-10.2 | Each recommendation shall disclose the observation window (start time, end time, sample count). |
| FR-10.3 | Each recommendation shall disclose its assumptions (e.g., target utilization percentage, headroom factor). |
| FR-10.4 | Recommendations shall be stored in PostgreSQL and served via the API. |

### FR-11: Health Check

| ID | Requirement |
|---|---|
| FR-11.1 | The backend shall expose a `/api/v1/health` endpoint returning connectivity status for the Kubernetes API, Prometheus, and PostgreSQL. |

## 2. Non-Functional Requirements

### NFR-1: Performance

| ID | Requirement |
|---|---|
| NFR-1.1 | Dashboard API responses shall complete within 3 seconds under normal cluster sizes (≤ 100 nodes, ≤ 2000 pods). |
| NFR-1.2 | Diagnostic sweeps shall complete within 30 seconds for the same cluster size. |
| NFR-1.3 | The frontend shall use TanStack Query caching to avoid redundant API calls. |

### NFR-2: Reliability

| ID | Requirement |
|---|---|
| NFR-2.1 | A Prometheus outage shall not crash the backend; affected data shall be reported as unavailable. |
| NFR-2.2 | A Kubernetes API outage shall not crash the backend; endpoints shall return partial data with clear error indicators. |
| NFR-2.3 | Database connection failures shall be retried with backoff. |

### NFR-3: Security

| ID | Requirement |
|---|---|
| NFR-3.1 | The backend shall perform read-only operations against the Kubernetes API. |
| NFR-3.2 | Kubeconfig, database credentials, and Prometheus URL shall never be exposed to the frontend. |
| NFR-3.3 | The backend shall never expose an endpoint for arbitrary PromQL execution. |
| NFR-3.4 | All user-supplied query parameters (namespace, time range) shall be validated. |
| NFR-3.5 | `.env` files shall never be committed to version control. |
| NFR-3.6 | The backend shall never retrieve Kubernetes Secret contents. |

### NFR-4: Observability

| ID | Requirement |
|---|---|
| NFR-4.1 | The backend shall emit structured JSON logs. |
| NFR-4.2 | The health endpoint shall report connectivity to all dependencies. |

### NFR-5: Testability

| ID | Requirement |
|---|---|
| NFR-5.1 | Diagnostic rules shall be unit-testable with synthetic input data (no live cluster required). |
| NFR-5.2 | The recommendation engine shall be independently testable. |
| NFR-5.3 | API routes shall have integration tests using FastAPI's TestClient. |
| NFR-5.4 | Frontend components shall have build verification and component tests. |

### NFR-6: Maintainability

| ID | Requirement |
|---|---|
| NFR-6.1 | The Kubernetes client, Prometheus client, diagnostics engine, and recommendation engine shall be separate modules. |
| NFR-6.2 | Database migrations shall be managed by Alembic. |
| NFR-6.3 | Every API response shall use a typed Pydantic schema. |

## 3. Constraints

| Constraint | Detail |
|---|---|
| Single cluster | The MVP monitors one Kubernetes cluster only. |
| Local development | The backend initially runs on the host, not inside the cluster. |
| No write operations | The MVP never mutates cluster state. |
| No raw PromQL | The backend constructs all Prometheus queries internally. |
| Windows development | The development environment is Windows with Docker Desktop and Minikube. |
