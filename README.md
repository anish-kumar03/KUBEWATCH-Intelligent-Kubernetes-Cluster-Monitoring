# KubeWatch

An intelligent Kubernetes cluster monitoring and performance
analysis system.

KubeWatch integrates with the Kubernetes API and Prometheus to
collect cluster state and metrics, detect operational problems
using deterministic diagnostic rules, and provide explainable,
evidence-backed resource optimization recommendations.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full
system design, component responsibilities, data flow, API
boundaries, and security model.

## Requirements

See [docs/requirements.md](docs/requirements.md) for functional
and non-functional requirements.

## Implementation Plan

See [docs/implementation-plan.md](docs/implementation-plan.md) for
the phased build sequence.

## Technology Stack

| Layer | Technologies |
|---|---|
| Frontend | React, TypeScript, Vite, Recharts, TanStack Query, Tailwind CSS |
| Backend | Python, FastAPI, Kubernetes Python client, HTTPX, Pydantic Settings, SQLAlchemy, Alembic |
| Database | PostgreSQL |
| Monitoring | Prometheus, kube-state-metrics, node-exporter |
| Development | Windows, Docker Desktop, Minikube, VS Code |

## Prerequisites

Before setting up the project, ensure the following are installed:

- **Python 3.11+**
- **Node.js 18+** and **npm**
- **Docker Desktop** (for PostgreSQL and Minikube)
- **Minikube** with a running cluster
- **kubectl** configured to talk to Minikube
- **Prometheus**, **kube-state-metrics**, and **node-exporter**
  deployed inside Minikube (e.g., via Helm chart
  `kube-prometheus-stack`)

## Local Development

### 1. Start infrastructure

```bash
# Start PostgreSQL
docker compose up -d

# Start Minikube (if not already running)
minikube start

# Port-forward Prometheus to localhost:9090
kubectl port-forward -n monitoring svc/prometheus-operated 9090:9090
```

### 2. Start the backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
alembic upgrade head           # Apply database migrations
uvicorn app.main:app --reload --port 8000
```

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

### 4. Open the app

Navigate to [http://localhost:5173](http://localhost:5173).

## Environment Variables

Copy `.env.example` to `.env` and adjust as needed. See
[docs/architecture.md#7-environment-variables](docs/architecture.md#7-environment-variables)
for the complete list.

| Variable | Default |
|---|---|
| `PROMETHEUS_URL` | `http://localhost:9090` |
| `DATABASE_URL` | `postgresql+psycopg://kubewatch:local_dev_only_change_me@127.0.0.1:5432/kubewatch` |
| `LOG_LEVEL` | `INFO` |
| `CORS_ORIGINS` | `["http://localhost:5173", "http://localhost:5174"]` |

> **Security:** Never commit `.env` files. The `.gitignore`
> already excludes them.

## Project Structure

```
kubewatch/
├── .github/
│   └── copilot-instructions.md    # AI coding assistant rules
├── backend/
│   ├── src/kubewatch/             # Python source package
│   │   ├── clients/               # Kubernetes and Prometheus clients
│   │   ├── diagnostics/           # Incident detection rules
│   │   ├── recommendations/       # Resource right-sizing engine
│   │   ├── schemas/               # Pydantic response models
│   │   ├── config.py              # Pydantic Settings
│   │   └── main.py                # FastAPI application
│   ├── alembic/                   # Database migrations
│   └── pyproject.toml             # Python dependencies
├── frontend/                      # React + Vite SPA
├── deploy/                        # Kubernetes manifests (future)
├── monitoring/                    # Prometheus / Grafana configs
├── tests/                         # Integration and e2e tests
├── docs/
│   ├── architecture.md
│   ├── implementation-plan.md
│   └── requirements.md
├── docker-compose.yml             # PostgreSQL for local dev
├── .env.example                   # Environment variable template
├── .gitignore
└── README.md
```

## License

*To be determined.*
