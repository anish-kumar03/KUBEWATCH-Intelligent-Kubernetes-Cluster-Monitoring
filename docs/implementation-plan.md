# KubeWatch — Implementation Plan

## Overview

This plan divides the MVP into six sequential phases. Each phase
produces a working increment that can be tested independently.
Dependencies flow forward: no phase requires work from a later
phase.

---

## Phase 0: Project Scaffolding and Local Environment

**Goal:** Establish the project structure, dependency manifests,
local development tooling, and verify connectivity to all external
systems.

### Tasks

| # | Task | Output |
|---|---|---|
| 0.1 | Create the backend Python package structure under `backend/`. | `backend/pyproject.toml`, `backend/src/kubewatch/` |
| 0.2 | Create `backend/pyproject.toml` with all Python dependencies (FastAPI, uvicorn, kubernetes, httpx, pydantic-settings, sqlalchemy, alembic, asyncpg, pytest, httpx for testing). Do **not** run `pip install` automatically. | Dependency manifest |
| 0.3 | Create `backend/src/kubewatch/config.py` with Pydantic Settings loading from env vars and `.env`. | Settings module |
| 0.4 | Create `backend/src/kubewatch/main.py` with a minimal FastAPI app exposing `GET /api/v1/health`. | Health endpoint |
| 0.5 | Initialize Alembic under `backend/alembic/`. | Migration infrastructure |
| 0.6 | Scaffold the frontend with Vite + React + TypeScript under `frontend/`. Do **not** run `npm install` automatically. | `frontend/package.json`, Vite config |
| 0.7 | Add a `docker-compose.yml` for PostgreSQL only (the backend and frontend run on the host). | Docker Compose file |
| 0.8 | Create a `.env.example` with all environment variables and safe defaults. | Template file |
| 0.9 | Write a smoke test that starts the FastAPI app and calls `/api/v1/health`. | `tests/test_health.py` |

### Exit criteria
- `uvicorn kubewatch.main:app` starts without errors.
- `GET /api/v1/health` returns `200 OK`.
- The Vite dev server starts and renders a placeholder page.
- PostgreSQL is reachable from the backend.

---

## Phase 1: Kubernetes Data Collection

**Goal:** Read live cluster state and expose it through API
endpoints.

### Tasks

| # | Task | Output |
|---|---|---|
| 1.1 | Create `backend/src/kubewatch/clients/kubernetes.py` — a thin wrapper around the `kubernetes` Python client that reads `~/.kube/config`. | K8s client module |
| 1.2 | Implement `list_nodes()` returning typed node data (name, status, capacity, allocatable). | Node collection |
| 1.3 | Implement `list_pods(namespace=None)` returning typed pod data (name, namespace, phase, restart count, resource requests/limits). | Pod collection |
| 1.4 | Implement `list_deployments(namespace=None)` returning typed deployment data (name, namespace, replicas, available, unavailable). | Deployment collection |
| 1.5 | Create Pydantic response schemas in `backend/src/kubewatch/schemas/`. | Typed schemas |
| 1.6 | Create API routes: `GET /api/v1/nodes`, `GET /api/v1/pods`, `GET /api/v1/deployments`. | REST endpoints |
| 1.7 | Add namespace query-parameter validation (regex whitelist). | Input validation |
| 1.8 | Write unit tests for the Kubernetes client using mocked `kubernetes` API responses. | Tests |
| 1.9 | Write integration tests for the API routes using FastAPI TestClient. | Tests |

### Exit criteria
- All three endpoints return live data from Minikube.
- Namespace filtering works correctly.
- Tests pass with mocked Kubernetes responses.

---

## Phase 2: Prometheus Metrics Integration

**Goal:** Query Prometheus for CPU and memory metrics and serve
them through the API.

### Tasks

| # | Task | Output |
|---|---|---|
| 2.1 | Create `backend/src/kubewatch/clients/prometheus.py` — an async HTTPX client for `KUBEWATCH_PROMETHEUS_URL`. | Prometheus client |
| 2.2 | Implement curated query functions for node-level CPU and memory (using standard Prometheus metrics exposed by node-exporter and kube-state-metrics). | Metric queries |
| 2.3 | Implement curated query functions for pod-level CPU and memory. | Metric queries |
| 2.4 | Implement time-range support with validation (max 7 days). | Time range handling |
| 2.5 | Handle Prometheus unavailability gracefully (return partial data, not 500). | Error handling |
| 2.6 | Create Pydantic schemas for metric time-series responses. | Typed schemas |
| 2.7 | Add metrics data to existing node and pod endpoints, or create dedicated metrics endpoints. | API integration |
| 2.8 | Build the `GET /api/v1/cluster/overview` endpoint aggregating nodes, pods, deployments, and cluster-wide utilization. | Overview endpoint |
| 2.9 | Write unit tests with mocked Prometheus HTTP responses. | Tests |

### Exit criteria
- Cluster overview endpoint returns live utilization data.
- Missing Prometheus data is reported as unavailable, not as zero.
- Time-range queries work correctly.
- Tests pass with mocked Prometheus responses.

### Note on Prometheus metrics
The exact metric names will be determined by inspecting the
metrics actually exposed by the Minikube Prometheus + kube-state-metrics
+ node-exporter deployment. Do **not** invent metric names ahead
of implementation.

---

## Phase 3: Diagnostics Engine

**Goal:** Detect common operational problems and store incidents
with structured evidence.

### Tasks

| # | Task | Output |
|---|---|---|
| 3.1 | Create the initial Alembic migration for the `incidents` table (id, type, severity, namespace, resource_name, evidence JSON, detected_at, resolved_at). | Migration + model |
| 3.2 | Create `backend/src/kubewatch/diagnostics/` package with a base rule interface. | Rule framework |
| 3.3 | Implement `RestartLoopRule`: detect pods exceeding `KUBEWATCH_RESTART_THRESHOLD` restarts. Evidence: restart count, last termination reason, exit code. | Rule |
| 3.4 | Implement `PendingPodRule`: detect pods in Pending phase. Evidence: scheduling conditions, event messages. | Rule |
| 3.5 | Implement `DeploymentAvailabilityRule`: detect deployments with unavailable replicas. Evidence: desired vs. available counts, conditions. | Rule |
| 3.6 | Create a diagnostics runner that executes all rules and persists new incidents to PostgreSQL. | Runner |
| 3.7 | Create `GET /api/v1/incidents` endpoint with severity and recency sorting. | API endpoint |
| 3.8 | Write unit tests for each rule using synthetic input (no live cluster). | Tests |
| 3.9 | Write integration test for the diagnostics runner. | Tests |

### Exit criteria
- Each diagnostic rule is independently unit-testable.
- Incidents are persisted to PostgreSQL with full evidence.
- The incidents API returns structured, evidence-backed records.
- Tests pass with synthetic data.

---

## Phase 4: Recommendation Engine

**Goal:** Generate resource right-sizing recommendations from
observed Prometheus metrics.

### Tasks

| # | Task | Output |
|---|---|---|
| 4.1 | Create the Alembic migration for the `recommendations` table (id, namespace, resource_name, container, current_request, current_limit, recommended_request, recommended_limit, observation_window, assumptions, created_at). | Migration + model |
| 4.2 | Create `backend/src/kubewatch/recommendations/` package. | Package |
| 4.3 | Implement the CPU recommendation calculator: compare observed P95/max usage against current requests/limits, apply a configurable headroom factor. | Calculator |
| 4.4 | Implement the memory recommendation calculator with the same structure. | Calculator |
| 4.5 | Ensure every recommendation discloses: observation start, observation end, sample count, headroom factor, target utilization. | Transparency metadata |
| 4.6 | Create `GET /api/v1/recommendations` endpoint. | API endpoint |
| 4.7 | Write unit tests for calculators with synthetic metric data. | Tests |
| 4.8 | Write integration test for the full recommendation pipeline. | Tests |

### Exit criteria
- Recommendations are generated from real Prometheus data.
- Every recommendation includes its observation window and assumptions.
- The recommendation engine is testable without a live cluster.
- Tests pass with synthetic metric data.

---

## Phase 5: Frontend Dashboard

**Goal:** Build the React frontend that consumes all backend APIs
and presents the monitoring data.

### Tasks

| # | Task | Output |
|---|---|---|
| 5.1 | Set up TanStack Query provider and API client module pointing at `localhost:8000`. | Data layer |
| 5.2 | Build the Cluster Overview page (node count, pod count, CPU/memory gauges, incident count). | Page |
| 5.3 | Build the Nodes page with a table and per-node utilization. | Page |
| 5.4 | Build the Pods page with namespace filtering and restart highlighting. | Page |
| 5.5 | Build the Deployments page with availability indicators. | Page |
| 5.6 | Build the Incidents page showing evidence-backed incident cards. | Page |
| 5.7 | Build the Recommendations page showing right-sizing suggestions with disclosed assumptions. | Page |
| 5.8 | Add Recharts time-series charts for CPU and memory metrics. | Charts |
| 5.9 | Configure CORS in the backend to allow `localhost:5173`. | CORS |
| 5.10 | Add Tailwind CSS and establish the visual design system. | Styling |
| 5.11 | Write frontend build verification and component tests. | Tests |

### Exit criteria
- All pages render live data from the backend.
- Charts display historical metric trends.
- Missing data is displayed as "unavailable" rather than zero.
- The frontend builds without errors.

---

## Phase 6: Integration Testing and Documentation

**Goal:** Validate the end-to-end system and finalize operational
documentation.

### Tasks

| # | Task | Output |
|---|---|---|
| 6.1 | Run end-to-end tests: frontend → backend → K8s + Prometheus + PostgreSQL. | Test results |
| 6.2 | Test graceful degradation: Prometheus down, Kubernetes API down. | Test results |
| 6.3 | Verify that no secrets leak through the API. | Security review |
| 6.4 | Finalize `README.md` with setup and run instructions. | Documentation |
| 6.5 | Write `docs/development-setup.md` with step-by-step local environment instructions. | Documentation |
| 6.6 | Create `deploy/kubernetes/` manifests for future in-cluster deployment (ServiceAccount, ClusterRole, Deployment). | K8s manifests |

### Exit criteria
- The full system works end-to-end on a local Minikube cluster.
- Graceful degradation is verified.
- Documentation is sufficient for a new developer to set up the project.

---

## Test Strategy Summary

| Layer | Tool | Scope |
|---|---|---|
| **Backend unit tests** | Pytest | Diagnostic rules, recommendation calculators, client wrappers — all with mocked external dependencies |
| **Backend integration tests** | Pytest + FastAPI TestClient | API routes with mocked K8s and Prometheus |
| **Database tests** | Pytest + test PostgreSQL | Incident and recommendation CRUD |
| **Frontend build** | Vite build | Compilation and type-checking |
| **Frontend component tests** | Vitest / React Testing Library | Component rendering and behavior |
| **End-to-end** | Manual + scripted | Full stack against live Minikube |

---

## Dependency Installation Note

This plan deliberately does **not** run `pip install` or
`npm install` automatically. Dependency manifests
(`pyproject.toml`, `package.json`) are created with the correct
entries, and the developer installs them explicitly.
