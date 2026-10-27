# KubeWatch — Architecture

## 1. Problem Statement

Operating a Kubernetes cluster requires continuous visibility into
resource consumption, workload health, and scheduling decisions.
Operators today must manually correlate signals across `kubectl`,
Prometheus dashboards, and pod logs to answer routine questions:

- Is the cluster running out of CPU or memory?
- Which pods are crash-looping, and why?
- Are any deployments under-provisioned or over-provisioned?
- Which pending pods cannot be scheduled, and what is blocking them?

KubeWatch automates this correlation. It continuously collects
cluster state from the Kubernetes API and time-series metrics from
Prometheus, detects common operational problems using deterministic
rules, and provides explainable, evidence-backed recommendations
for resource tuning.

## 2. Product Scope

### In scope (MVP)

| Capability | Description |
|---|---|
| Cluster overview | Aggregated node count, pod count, CPU/memory utilization |
| Node list | Per-node status, capacity, allocatable resources, current usage |
| Pod list | Per-pod status, restart count, resource requests/limits, age |
| Deployment list | Per-deployment replicas, availability, update status |
| CPU & memory metrics | Current and historical utilisation via Prometheus |
| Restart detection | Pods exceeding a configurable restart-count threshold |
| Pending-pod detection | Pods stuck in Pending with reason extraction |
| Availability detection | Deployments with unavailable replicas |
| Evidence-backed incidents | Structured records linking a problem to its evidence |
| Resource recommendations | CPU/memory right-sizing suggestions with disclosed assumptions |

### Explicitly excluded from MVP

| Feature | Reason |
|---|---|
| Automatic workload remediation | Safety: MVP is read-only |
| New time-series database | Prometheus already provides metrics history |
| Multi-cloud management | Scope: single-cluster monitoring only |
| LLM-based diagnosis | Complexity: deterministic rules first |
| Supervised machine learning | Complexity: heuristic thresholds first |
| Multi-tenant SaaS billing | Scope: single-operator deployment first |

## 3. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser (React SPA)                      │
│  Vite · TypeScript · Recharts · TanStack Query · Tailwind CSS   │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP JSON (localhost:5173 → :8000)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend (Python)                     │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │ API Routes   │  │ Diagnostics  │  │ Recommendation Engine │  │
│  │ (read-only)  │  │ Engine       │  │                       │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────┬───────────┘  │
│         │                 │                      │              │
│  ┌──────▼─────────────────▼──────────────────────▼───────────┐  │
│  │              Collector Layer                               │  │
│  │  ┌─────────────────────┐  ┌────────────────────────────┐   │  │
│  │  │ Kubernetes Client   │  │ Prometheus Client (HTTPX)  │   │  │
│  │  │ (kubernetes-python) │  │                            │   │  │
│  │  └─────────┬───────────┘  └─────────────┬──────────────┘   │  │
│  └────────────┼────────────────────────────┼──────────────────┘  │
│               │                            │                    │
└───────────────┼────────────────────────────┼────────────────────┘
                │                            │
     ┌──────────▼──────────┐    ┌────────────▼────────────┐
     │   Kubernetes API    │    │   Prometheus (9090)      │
     │   (Minikube)        │    │   kube-state-metrics     │
     │                     │    │   node-exporter          │
     └─────────────────────┘    └─────────────────────────┘

                 ┌──────────────────────┐
                 │  PostgreSQL (5432)   │
                 │  incidents           │
                 │  recommendations     │
                 │  application config  │
                 └──────────────────────┘
```

## 4. Component Responsibilities

### 4.1 Frontend (React SPA)

| Concern | Detail |
|---|---|
| **Runtime** | Vite dev server on `localhost:5173` |
| **Rendering** | React with TypeScript, component-based UI |
| **Data fetching** | TanStack Query → backend REST API |
| **Charts** | Recharts for CPU/memory time-series |
| **Styling** | Tailwind CSS |
| **Security boundary** | Never receives kubeconfig, DB creds, or raw PromQL |

The frontend is a pure presentation layer. It does **not**:
- Query Prometheus directly.
- Call the Kubernetes API directly.
- Execute any write operations against the cluster.

### 4.2 Backend (FastAPI)

The backend is the single authority for data aggregation, analysis,
and access control. It exposes a versioned REST API consumed
exclusively by the frontend.

#### Sub-components

| Module | Responsibility |
|---|---|
| **API routes** | Serve aggregated data to the frontend. Validate query params (namespace, workload, time range). |
| **Kubernetes client** | Read cluster state: nodes, pods, deployments, events. Uses the `kubernetes` Python client and reads `~/.kube/config` during local development. |
| **Prometheus client** | Execute curated PromQL queries via HTTPX against Prometheus's HTTP API. Never exposes raw arbitrary PromQL to users. |
| **Diagnostics engine** | Deterministic rules that detect restart-looping pods, pending pods, unavailable deployments, and resource pressure. Each rule must cite its evidence. |
| **Recommendation engine** | Compute right-sizing suggestions from observed metrics. Must disclose the observation window and assumptions. Independently testable. |
| **Database layer** | SQLAlchemy models + Alembic migrations for PostgreSQL. Stores incidents, recommendations, and application data. Does **not** store raw Prometheus time-series. |
| **Settings** | Pydantic Settings reading from environment variables with `.env` file support. |

### 4.3 PostgreSQL Persistence Layer

Stores **application state only**:
- **`incidents`**: Stable UUID, cluster identifier, resource coordinates (type, namespace, name), rule identifier, severity, title, description, first and last observed timestamps, status (active, acknowledged, resolved), and resolution timestamp.
- **`incident_evidence`**: Foreign key to parent incident (`ON DELETE CASCADE`), evidence type (`metric_breach`, `k8s_event`, `log_pattern`), human-readable summary, observation time, and JSON structured source metadata.
- **`resource_recommendations`**: Affected workload coordinates, recommendation type (`cpu_request`, `memory_limit`, etc.), observation window, JSON current configuration summary, JSON measured usage summary, recommendation text, and review status (`pending`, `applied`, `dismissed`).
- **`detection_rules`**: Rule identifier slug, human-readable name, description, default severity, active toggle (`enabled`), and dynamic JSON threshold configuration.

**Key Persistence Rules:**
- Database connections use SQLAlchemy 2.x with the modern `psycopg` (v3) driver (`postgresql+psycopg://...`).
- Schema migrations are managed declaratively via Alembic (`alembic upgrade head`).
- Migrations never destroy, reset, or wipe existing databases.
- Prometheus remains the sole system of record for raw time-series metrics. PostgreSQL stores only aggregated, contextualized summaries needed for tracking history, investigations, and workflow reviews.

### 4.4 Prometheus Stack (Minikube)

| Component | Role |
|---|---|
| **Prometheus** | Scrapes and stores time-series metrics |
| **kube-state-metrics** | Exposes Kubernetes object state as Prometheus metrics |
| **node-exporter** | Exposes host-level CPU, memory, disk, and network metrics |

Prometheus is accessed from the host via `kubectl port-forward`
on `localhost:9090` during local development.

## 5. Data Flow

### 5.1 Dashboard Request (synchronous)

```
Browser  ──GET /api/v1/cluster/overview──▶  FastAPI
                                              │
                              ┌───────────────┼───────────────┐
                              ▼               ▼               ▼
                        K8s API         Prometheus       PostgreSQL
                       (nodes,         (CPU/mem         (incidents,
                        pods,           queries)         recs)
                        deploys)
                              │               │               │
                              └───────┬───────┘               │
                                      ▼                       │
                                 Aggregation ◄────────────────┘
                                      │
                                      ▼
Browser  ◄──────── JSON response ─────┘
```

### 5.2 Diagnostics Sweep (periodic / on-demand)

```
Scheduler or API trigger
        │
        ▼
  Diagnostics Engine
        │
        ├──▶ K8s API  (pod status, events, conditions)
        ├──▶ Prometheus (recent CPU/mem, restart counters)
        │
        ▼
  Rule evaluation
        │
        ├── restart_loop_rule   → evidence: restartCount, lastState
        ├── pending_pod_rule    → evidence: conditions, events
        ├── availability_rule   → evidence: unavailableReplicas
        ├── resource_pressure   → evidence: node CPU/mem %
        │
        ▼
  New incidents ──▶ PostgreSQL (INSERT)
        │
        ▼
  Recommendations ──▶ PostgreSQL (UPSERT)
```

## 6. API Boundaries

All endpoints are prefixed with `/api/v1`. Every response uses
a typed Pydantic schema.

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/cluster/overview` | Aggregated cluster summary |
| GET | `/api/v1/nodes` | Node list with status and utilization |
| GET | `/api/v1/pods` | Pod list, filterable by namespace |
| GET | `/api/v1/deployments` | Deployment list with availability |
| GET | `/api/v1/incidents` | Detected incidents with evidence |
| GET | `/api/v1/recommendations` | Resource right-sizing suggestions |
| GET | `/api/v1/health` | Backend health check |

Query parameters for filtering (namespace, time range) will be
validated with Pydantic models. Invalid or out-of-range values
return `422 Unprocessable Entity`.

## 7. Environment Variables

All configuration is read through Pydantic Settings with `.env`
file support. Defaults are tuned for local development.

| Variable | Default | Description |
|---|---|---|
| `KUBEWATCH_PROMETHEUS_URL` | `http://localhost:9090` | Prometheus base URL |
| `DATABASE_URL` / `KUBEWATCH_DATABASE_URL` | `postgresql+psycopg://kubewatch:local_dev_only_change_me@127.0.0.1:5432/kubewatch` (dev only) | PostgreSQL connection string via psycopg 3 driver |
| `KUBEWATCH_KUBE_CONTEXT` | *(current context)* | Kubernetes context to use |
| `KUBEWATCH_LOG_LEVEL` | `INFO` | Python logging level |
| `KUBEWATCH_CORS_ORIGINS` | `http://localhost:5173` | Allowed CORS origins |
| `KUBEWATCH_DIAGNOSTICS_INTERVAL_SECONDS` | `60` | Interval between diagnostic sweeps |
| `KUBEWATCH_RESTART_THRESHOLD` | `5` | Restart count threshold for incident |

## 8. Security Boundaries

### 8.1 Read-Only Cluster Access

The MVP backend performs **no write operations** against the
Kubernetes API. It uses only:
- `list` / `get` on Nodes, Pods, Deployments, Events, ReplicaSets

When deployed inside the cluster, it will use a ServiceAccount with
a ClusterRole restricted to those verbs.

### 8.2 Credential Isolation

| Credential | Where it lives | Frontend access |
|---|---|---|
| Kubeconfig | Host filesystem or ServiceAccount mount | **Never** |
| PostgreSQL connection string | Environment variable / `.env` | **Never** |
| Prometheus URL | Environment variable / `.env` | **Never** |

### 8.3 Input Validation

- Namespace parameters are validated against a whitelist pattern.
- Time-range parameters are bounded (e.g., max 7 days).
- No arbitrary PromQL passthrough to Prometheus.

### 8.4 .env and Secrets Hygiene

- `.env` files are listed in `.gitignore`.
- No secrets are committed to the repository.
- Docker images do not embed `.env` files.

## 9. Deployment Topology

### 9.1 Local Development (current)

| Component | Runs on | Port |
|---|---|---|
| Frontend (Vite) | Host | 5173 |
| Backend (FastAPI / Uvicorn) | Host | 8000 |
| PostgreSQL | Docker Desktop | 5432 |
| Prometheus | Minikube (port-forwarded) | 9090 |
| Kubernetes API | Minikube | 6443 (via kubeconfig) |

### 9.2 In-Cluster (future)

The backend will be deployed as a Kubernetes Deployment with a
read-only ServiceAccount. PostgreSQL will run as a StatefulSet
or be replaced by a managed database. The frontend will be served
as static files from an Nginx container or a CDN.

## 10. Key Design Decisions

| Decision | Rationale |
|---|---|
| Prometheus for metrics, PostgreSQL for incidents | Avoids duplicating time-series storage; each database does what it does best. |
| Deterministic diagnostic rules (no ML) | Explainability, auditability, and simplicity for MVP. |
| Backend queries Prometheus, frontend does not | Single point of query control and credential isolation. |
| Curated PromQL, no raw query passthrough | Prevents injection and limits Prometheus load. |
| Pydantic schemas for every API response | Type safety across the stack; frontend can generate TypeScript types. |
| Read-only Kubernetes access | Safety: the monitoring system must never modify the cluster it observes. |
| SQLAlchemy + Alembic | Mature ORM with migration support, consistent with FastAPI ecosystem. |
| Tailwind CSS | Listed in copilot-instructions.md; utility-first CSS for rapid UI development. |
