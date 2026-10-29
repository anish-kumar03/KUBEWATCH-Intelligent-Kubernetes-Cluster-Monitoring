# KubeWatch — Testing & Reliability Review

This document provides a comprehensive report on the testing strategy, verification procedures, error handling mechanisms, and reliability guarantees of the KubeWatch application.

---

## 1. Testing Strategy & Architecture

KubeWatch employs a multi-layered testing pyramid designed to ensure high deterministic reliability without requiring a live production Kubernetes cluster for everyday CI/CD and developer workflows:

1. **Deterministic Unit Tests**:
   - All diagnostic rules, mathematical calculators, and quantity parsers execute against synthetic, typed inputs.
   - Database tests execute against an in-memory SQLite database using `StaticPool` for complete transactional isolation.
2. **API & Contract Tests**:
   - FastAPI `TestClient` tests evaluate every endpoint, query parameter validation, and HTTP error response.
   - Custom exception handlers guarantee uniform `ApiResponse` envelope serialization across all endpoints (`/api` and `/api/v1`).
3. **Frontend Build & Static Analysis**:
   - TypeScript compiler (`tsc -b`) verifies complete type alignment between backend JSON payloads and frontend models.
   - Vite produces clean production bundles without compilation errors.
   - ESLint enforces strict React hooks and code quality rules.

---

## 2. Review of Testing Requirements

### 2.1 Backend Unit Tests
* **Status**: **PASSED** (119 passed, 1 skipped)
* **Scope**:
  - `test_config.py`: Settings parsing, environment overrides, Kubernetes mode enum validation, CORS list parsing.
  - `test_kubernetes_service.py`: CPU/memory quantity parsing (cores, millicores, binary/decimal SI units), connection error handling, read-only API calls.
  - `test_prometheus_service.py`: Query sanitization, scalar extraction, matrix/vector parsing, timeouts, connection errors.
  - `test_database.py`: SQLAlchemy models, foreign key cascading, JSON serialization, transaction rollback, session scopes, 503 error handling.
  - `test_diagnostics.py`: All 5 diagnostic rules, evidence generation, incident deduplication, fingerprint stability, auto-recovery lifecycle, API routes.
  - `test_recommendations.py`: Mathematical statistics (p95 linear interpolation, average, peak, completeness ratio), CPU/memory right-sizing heuristics, limit risk detection, insufficient data advisories, review status transitions.
  - `test_health.py`: Health endpoint status aggregation, degradation detection, timestamps.
  - `test_routes.py`: Cluster overview, node list, pod list, deployment list, namespace filtering, and error envelopes.

### 2.2 Frontend Build and Tests
* **Status**: **PASSED**
* **Verification**:
  - `npm --prefix frontend run build`: Transpiles 2,568 modules cleanly via Vite and TypeScript (`tsc -b`).
  - `npm --prefix frontend run lint`: Zero ESLint warnings or errors.
  - Component models align with API response contracts.

### 2.3 API Contracts Between Frontend and Backend
* **Status**: **VERIFIED**
* **Findings**:
  - Dual Prefix Routing: All routes are mounted under both `/api` (used by React SPA) and `/api/v1` (specified in architecture docs).
  - Schema Alignment:
    - `IncidentInfo`: Supports `active`, `acknowledged`, and `resolved` lifecycle states.
    - `RecommendationInfo`: Computed fields on `ResourceRecommendationRead` (`status`, `resource_type`, `current_spec`, `recommended_spec`, `reasoning`, `estimated_savings`) map directly to frontend card requirements.
    - Uniform Envelope: All endpoints return `ApiResponse<T>` (`status`, `data`, `error`, `timestamp`).
  - Error Parsing: Frontend `apiClient` extracts both `error` and FastAPI `detail` fields, preventing opaque HTTP status errors.

### 2.4 Database Model & Migration Consistency
* **Status**: **VERIFIED**
* **Findings**:
  - Migration Revision: `d881ba04c0cb` represents the current schema head.
  - Model Sync:
    - `incidents`: Indices on `cluster_id`, `namespace`, `rule_identifier`, `status`, `last_observed_at`.
    - `incident_evidence`: Foreign key `incident_id` with `ondelete="CASCADE"`.
    - `resource_recommendations`: Compound index on `(cluster_id, namespace, workload_type, workload_name)` and status index on `(review_status, recommendation_type)`.
    - `detection_rules`: Configurable threshold JSON storage and enabled toggles.

### 2.5 Incident Deduplication and Lifecycle Behavior
* **Status**: **VERIFIED**
* **Findings**:
  - Fingerprint Stability: Stable UUIDv5 generated from `(cluster_id, namespace, resource_type, resource_name, rule_identifier)`.
  - Deduplication: Repeated evaluations update `last_observed_at` and append new evidence without duplicating records.
  - Lifecycle:
    - Open incidents transition from `active` to `acknowledged`.
    - Incidents auto-resolve when the triggering condition clears (e.g. pending pod transitions to Running, deployment replicas recover, node pressure clears).
    - Incidents can be manually resolved via `/api/v1/incidents/{id}/resolve`.

### 2.6 Rule Behavior When Metrics Are Absent
* **Status**: **VERIFIED**
* **Findings**:
  - Missing metrics are **never interpreted as zero**.
  - `HighMemoryUtilizationRule`: Skips containers when Prometheus is listed under `unavailable_sources` or when working set metrics are missing. Does NOT falsely trigger or auto-resolve.
  - Recommendation Engine: Sizing is suppressed when telemetry has fewer than 12 samples, shorter than 6 hours duration, or completeness below 50%. Emits an explicit `insufficient_historical_data` advisory notice.

### 2.7 Error Handling When Prometheus Is Unavailable
* **Status**: **VERIFIED**
* **Findings**:
  - `/api/cluster/overview`: CPU and memory utilization fall back to `None` (`null` in JSON) rather than zero.
  - `/api/metrics/*`: Returns `status="error"` with human-readable error description; backend does not crash.
  - UI Indicators: Prometheus status badge reflects `Offline`, and chart widgets display `Metrics Offline` empty states.

### 2.8 Error Handling When Kubernetes Is Unreachable
* **Status**: **VERIFIED**
* **Findings**:
  - Service Layer: Catches `ApiException` and wraps into typed `KubernetesApiError` or `KubernetesConnectionError`.
  - Route Layer: Returns `status="error"` with clean error details across `/nodes`, `/pods`, `/deployments`, and `/cluster/overview`.
  - Scheduler: Background diagnostics loop logs warnings and backs off without crashing the FastAPI process.

### 2.9 Error Handling When PostgreSQL Is Unavailable
* **Status**: **VERIFIED**
* **Findings**:
  - Dependency Layer: `get_db` raises HTTP 503 Service Unavailable when `DATABASE_URL` is empty or engine connectivity fails.
  - Exception Handler: Custom `HTTPException` handler in `main.py` converts 503 errors into a uniform `ApiResponse` envelope:
    ```json
    {
      "status": "error",
      "data": null,
      "error": "Database service is currently unreachable.",
      "timestamp": "2026-10-29T23:00:00Z"
    }
    ```
  - Transaction Isolation: `session_scope` performs automatic rollback on any database exception.

### 2.10 Input Validation & Query-Range Restrictions
* **Status**: **VERIFIED**
* **Findings**:
  - Namespace Validation: Regex `^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$` prevents invalid or hostile namespace strings.
  - Resource Names: Regex `^[a-z0-9]([a-z0-9\-\.]{0,252}[a-z0-9])?$` enforces DNS subdomain limits.
  - Time Range Limits: Validates `start < end` and enforces maximum historical lookback of 168 hours (7 days).
  - PromQL Injection Prevention: `_sanitize_label` strips all characters outside alphanumeric, `-`, `_`, `.`, and `.*`.

---

## 3. Test Execution Commands & Results

### Execute Full Backend Test Suite
```powershell
backend\.venv\Scripts\pytest.exe -c backend\pytest.ini -v
```
**Output**: `119 passed, 1 skipped in 17.35s` (PostgreSQL live integration test skipped when external port 5432 is down).

### Execute Frontend Build & Lint Verification
```powershell
# Type-check and production bundle build
npm --prefix frontend run build

# Static code quality and ESLint rules
npm --prefix frontend run lint
```
**Output**: Zero compilation errors; production assets built in `frontend/dist/`.

---

## 4. Unresolved Items & Observations

1. **Frontend Automated Component Tests**:
   - The frontend currently relies on TypeScript compilation (`tsc -b`) and ESLint for static verification. Automated Jest/Vitest unit tests for individual React components are not yet present in `frontend/src`.
2. **Prometheus High Availability / Downsampling**:
   - Prometheus range queries currently pull directly from Prometheus storage. If Prometheus retention is short (e.g. 24h), queries beyond retention return empty datasets rather than downsampled aggregates.

