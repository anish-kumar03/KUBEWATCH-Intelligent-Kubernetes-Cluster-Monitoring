# KubeWatch - GitHub Copilot Instructions

## Project Overview

KubeWatch is an intelligent Kubernetes monitoring and performance
analysis system.

The system integrates with Kubernetes and Prometheus to collect
cluster state and metrics, detect operational problems, correlate
evidence, and provide explainable resource optimization recommendations.

## Technology Stack

Frontend:
- React
- TypeScript
- Vite
- Recharts
- TanStack Query
- Tailwind CSS

Backend:
- Python
- FastAPI
- Kubernetes Python client
- HTTPX
- Pydantic Settings
- SQLAlchemy
- Alembic

Database:
- PostgreSQL

Monitoring:
- Kubernetes API
- Prometheus
- kube-state-metrics
- Node Exporter

Testing:
- Pytest
- Frontend build and component tests

## Architecture Requirements

- Keep frontend and backend responsibilities separate.
- Keep Kubernetes integration separate from Prometheus integration.
- Keep diagnostic rules separate from API routes.
- Keep the recommendation engine independently testable.
- Do not store every Prometheus timeseries in PostgreSQL.
- Use Prometheus for metrics history.
- Use PostgreSQL for incidents, recommendations, and application data.
- Define typed API response schemas.
- Validate incoming user input.

## Data Integrity

- Never invent real cluster measurements.
- Never use hardcoded sample metrics as live production data.
- Missing metrics must not be interpreted as zero.
- Unavailable data sources must be reported explicitly.
- Clearly distinguish observed facts from possible explanations.
- Every diagnostic explanation must identify its supporting evidence.
- Recommendations must disclose their observation window and assumptions.

## Security

- The initial monitoring functionality must be read-only.
- Never delete pods or modify workloads automatically.
- Never retrieve Kubernetes Secret contents for the initial MVP.
- Do not expose kubeconfig credentials or database credentials to the frontend.
- Never commit .env files containing credentials.
- Use least-privilege Kubernetes permissions for deployment.
- Do not expose unrestricted arbitrary Prometheus queries to users.
- Validate namespace, workload, and time-range parameters.

## Development Workflow

- Implement one phase at a time.
- Inspect the existing code before modifying it.
- Preserve working functionality.
- Do not rewrite unrelated files.
- Add tests for new behavior.
- Do not remove tests simply to make builds pass.
- Run relevant tests and builds after making changes.
- Explain any failed tests honestly.
- Do not claim a feature works unless it has been tested.
- Prefer simple implementations over unnecessary abstractions.
- Do not add an LLM, Redis, or machine-learning model without a
  specific requirement.
- Document environment variables and installation commands.