# KubeWatch Backend

The FastAPI-based backend service for KubeWatch: An Intelligent Kubernetes Cluster Monitoring and Performance Analysis System.

## Architectural Boundaries

- **`app/core/config.py`**: Centralized configuration management using Pydantic Settings and environment variables. Reads `DATABASE_URL`, `KUBERNETES_MODE`, `PROMETHEUS_URL`, etc. Never hardcodes credentials.
- **`app/db/`**:
  - `base.py`: SQLAlchemy 2.x `DeclarativeBase` metadata.
  - `session.py`: Connection pooling (`pool_pre_ping=True`, size=5, max_overflow=10), sessionmaker factory, transactional `session_scope()`, FastAPI `get_db` dependency, and `check_db_health()`.
- **`app/models/`**:
  - `incident.py`: `Incident` (cluster ID, resource coordinates, rule identifier, status lifecycle, resolution time) and `IncidentEvidence` (1-to-many relationship, cascade on delete, JSON source metadata).
  - `recommendation.py`: `ResourceRecommendation` (affected workload, sizing recommendation type, observation window, JSON current/measured configuration, review status).
  - `rule.py`: `DetectionRule` (rule identifier, name, severity, enabled toggle, JSON threshold config).
- **`app/schemas/`**: Strict typed Pydantic models with uniform `ApiResponse` envelope (`models.py`) and persistence schemas (`persistence.py`). Missing metrics are represented as `null`, never as zero.
- **`app/services/kubernetes_service.py`**: Read-only facade over the official Kubernetes Python client. Supports both local kubeconfig (`local`) and in-cluster service account (`in_cluster`) modes without silent fallbacks. Never reads Kubernetes Secrets.
- **`app/services/prometheus_service.py`**: Async HTTPX client for Prometheus. Restricts metric queries to validated, curated PromQL templates to prevent arbitrary injection.
- **`app/api/routes/`**: Clean separation of route endpoints:
  - `health.py`: Readiness/liveness checks verifying Kubernetes and Prometheus connectivity.
  - `cluster.py`: Cluster-wide summary (node count, pod count, namespaces, capacity, usage).
  - `nodes.py`: Node status, roles, capacity, allocatable resources, and conditions.
  - `pods.py`: Pod listing with optional namespace filter, phases, restarts, and container metrics.
  - `deployments.py`: Deployment status and replica counts with optional namespace filter.
  - `metrics.py`: Curated CPU and memory metrics for nodes and pods (instant and range).

---

## Local Development Setup

### 1. Prerequisites

- Python 3.10+ (tested on Python 3.12)
- Minikube or another local Kubernetes cluster
- Prometheus running and port-forwarded (`kubectl port-forward -n monitoring svc/prometheus-k8s 9090:9090`)
- PostgreSQL 16 (running via Docker or local service)

### 2. Virtual Environment Setup

Create and activate a Python virtual environment:

#### Windows (PowerShell)
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

#### Linux / macOS
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure Environment

Copy the example environment configuration:

```bash
cp .env.example .env
```

Set the database connection string in `.env`:
```env
DATABASE_URL=postgresql+psycopg://kubewatch:local_dev_only_change_me@127.0.0.1:5432/kubewatch
```
*(The URL must always be loaded from the environment and never hardcoded in source code.)*

---

## Database Migrations (Alembic)

KubeWatch uses Alembic for declarative schema migrations. Migrations do not reset or destroy existing data.

### Running Migrations

Apply all outstanding migrations to head:
```bash
alembic upgrade head
```

Revert the most recent migration:
```bash
alembic downgrade -1
```

Check current database migration version:
```bash
alembic current
```

View migration history:
```bash
alembic history --verbose
```

### Creating New Migrations

After modifying or adding models in `app/models/`:
```bash
alembic revision --autogenerate -m "describe_migration_here"
```
Review the generated file in `alembic/versions/` and apply with `alembic upgrade head`.

---

## Running the Backend

Start the development server using `uvicorn`:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be accessible at:
- **Root/Docs**: `http://localhost:8000/docs` (Swagger UI)
- **ReDoc**: `http://localhost:8000/redoc`
- **Health Check**: `http://localhost:8000/api/health`

---

## Running Tests

Run the complete test suite using `pytest`:

```bash
pytest tests/ -v
```

### Running Tests Without a Database (In-Memory Unit Tests)
```bash
pytest tests/ -v -m "not integration"
```
All unit tests execute against an in-memory SQLite engine (`sqlite:///:memory:`) with complete model, constraint, cascade, and transaction rollback verification.

### Running PostgreSQL Integration Tests
```bash
pytest tests/ -v -m "integration"
```
Integration tests connect to the local PostgreSQL instance, verify table persistence and cleanup, and automatically skip if PostgreSQL is unavailable without breaking CI pipelines.
