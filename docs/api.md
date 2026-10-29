# KubeWatch — API Reference

This document details the REST API endpoints exposed by the KubeWatch backend (`/api/v1` and `/api`).

All endpoints return a uniform `ApiResponse` envelope:

```json
{
  "status": "ok",
  "data": { ... },
  "error": null,
  "timestamp": "2026-10-27T14:30:00Z"
}
```

---

## 1. Incidents API

The Incidents API provides access to rule-based operational findings, supporting normalized evidence, and lifecycle transitions.

### 1.1 List Incidents

`GET /api/v1/incidents`  
`GET /api/incidents`

Returns a list of detected incidents sorted by severity priority (critical → warning → info) and recency (`last_observed_at` descending).

#### Query Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `status` | string | `null` | Filter by lifecycle status: `active`, `acknowledged`, `resolved` |
| `severity` | string | `null` | Filter by severity: `critical`, `warning`, `info` |
| `namespace` | string | `null` | Filter by Kubernetes namespace |
| `resource_type` | string | `null` | Filter by resource type: `Pod`, `Deployment`, `Node` |
| `rule_identifier` | string | `null` | Filter by detection rule slug |
| `cluster_id` | string | `null` | Filter by cluster identifier |
| `limit` | integer | `50` | Maximum items to return (1 - 200) |
| `offset` | integer | `0` | Number of items to skip |

#### Example Response

```json
{
  "status": "ok",
  "data": [
    {
      "id": "e4b6d39e-26a1-5d9c-8517-56ec02efd297",
      "cluster_id": "development",
      "resource_type": "Pod",
      "namespace": "production",
      "resource_name": "payment-service-89fbc-x2",
      "rule_identifier": "container-restart-activity",
      "rule_name": "container-restart-activity",
      "severity": "critical",
      "title": "Pod payment-service-89fbc-x2 has elevated container restart activity (16 restarts)",
      "message": "Pod payment-service-89fbc-x2 has elevated container restart activity (16 restarts)",
      "description": "### Observed Fact\nPod has restarted 16 times...\n\n### Recommended Next Steps\n  1. Check previous logs...",
      "first_observed_at": "2026-10-27T14:00:00Z",
      "last_observed_at": "2026-10-27T14:15:00Z",
      "observed_at": "2026-10-27T14:15:00Z",
      "status": "active",
      "resolution_time": null,
      "created_at": "2026-10-27T14:00:00Z",
      "updated_at": "2026-10-27T14:15:00Z",
      "evidence": [
        {
          "id": "7ac16892-0b1a-46ae-9529-61feea7ea988",
          "incident_id": "e4b6d39e-26a1-5d9c-8517-56ec02efd297",
          "evidence_type": "container_state",
          "summary": "Container 'payment-app' has restarted 16 times; state: terminated: OOMKilled (137)",
          "observation_time": "2026-10-27T14:15:00Z",
          "source_metadata": {
            "source_type": "kubernetes_api",
            "measured_value": { "restart_count": 16, "ready": false },
            "relevant_configuration": { "restart_threshold": 5 },
            "explanation": "Restart count 16 exceeds threshold 5."
          },
          "created_at": "2026-10-27T14:15:00Z"
        }
      ]
    }
  ],
  "error": null,
  "timestamp": "2026-10-27T14:15:05Z"
}
```

---

### 1.2 Retrieve Incident Details

`GET /api/v1/incidents/{incident_id}`  
`GET /api/incidents/{incident_id}`

Returns the full incident record matching `incident_id`, including all associated evidence items.

#### Status Codes
* `200 OK`: Incident found.
* `404 Not Found`: Incident with specified ID does not exist.

---

### 1.3 Acknowledge Incident

`POST /api/v1/incidents/{incident_id}/acknowledge`  
`POST /api/incidents/{incident_id}/acknowledge`

Transitions an `active` incident to `acknowledged`. Indicates operator awareness while keeping the incident open.

#### Status Codes
* `200 OK`: Incident successfully acknowledged.
* `400 Bad Request`: Cannot acknowledge an already resolved incident.
* `404 Not Found`: Incident with specified ID does not exist.

---

### 1.4 Resolve Incident

`POST /api/v1/incidents/{incident_id}/resolve`  
`POST /api/incidents/{incident_id}/resolve`

Manually marks an incident as `resolved`, recording the current UTC timestamp as `resolution_time`.

#### Status Codes
* `200 OK`: Incident resolved.
* `404 Not Found`: Incident with specified ID does not exist.

---

### 1.5 Trigger Diagnostic Sweep On-Demand

`POST /api/v1/incidents/sweep`  
`POST /api/incidents/sweep`

Forces an immediate execution of all diagnostic rules and persistence updates.

#### Example Response

```json
{
  "status": "ok",
  "data": {
    "status": "ok",
    "summary": {
      "evaluated_rules": 5,
      "flagged_candidates": 2,
      "persisted_new": 0,
      "updated_existing": 2,
      "auto_resolved": 1
    }
  },
  "error": null,
  "timestamp": "2026-10-27T14:20:00Z"
}
```



---

## 2. Resource Recommendations API

The Recommendations API provides access to data-driven container sizing advisory suggestions, review lifecycle tracking, and on-demand evaluation sweeps.

### 2.1 List Recommendations

`GET /api/v1/recommendations`  
`GET /api/recommendations`

Returns advisory recommendations ordered by recency (`created_at` descending).

#### Query Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `status` | string | `null` | Filter by review status: `open` (`pending`), `applied`, `dismissed` |
| `namespace` | string | `null` | Filter by Kubernetes namespace |
| `workload_type` | string | `null` | Filter by workload kind: `Deployment`, `Pod`, `StatefulSet` |
| `workload_name` | string | `null` | Filter by workload name |
| `recommendation_type` | string | `null` | Filter by type: `cpu_underutilization`, `memory_underutilization`, `high_memory_limit_utilization`, `insufficient_historical_data` |
| `cluster_id` | string | `null` | Filter by cluster identifier |
| `limit` | integer | `50` | Maximum items to return (1 - 200) |
| `offset` | integer | `0` | Number of items to skip |

#### Example Response

```json
{
  "status": "ok",
  "data": [
    {
      "id": "2e698ea4-81c3-4b37-b0c5-45fafe3b8976",
      "cluster_id": "production",
      "namespace": "default",
      "workload_type": "Deployment",
      "workload_name": "checkout-service",
      "container_name": "checkout",
      "recommendation_type": "cpu_underutilization",
      "observation_window": "24h",
      "status": "open",
      "resource_type": "Deployment",
      "current_spec": {
        "cpu_request": "1000m"
      },
      "recommended_spec": {
        "cpu_request": "125m"
      },
      "reasoning": "### Workload & Container\nWorkload `Deployment/default/checkout-service` (container `checkout`).\n\n### Observation Period & Telemetry\n- Observation duration: 24.0 hours (200 valid samples, 69.4% data completeness).\n- Measured CPU usage: average 80m, p95 100m, peak 150m.\n\n### Current Configuration vs Measured Utilization\n- Configured CPU request: `1000m` (1000m).\n- Workload consumed only 10.0% of its reserved CPU request at p95 over the observation period.\n\n### Proposed Action\n- Right-size CPU request from `1000m` to `125m` (includes 25% safety headroom above measured p95).\n- Frees 875m of cluster allocatable CPU capacity for other workloads.\n\n### Assumptions & Risk Assessment\n- Assumes observed 24.0h window captures typical peak workload traffic without pending batch spikes.\n- Cost Disclaimer: Reducing CPU requests increases pod scheduling density and frees node allocatable capacity; cloud billing reduction depends on whether overall cluster node count can be downscaled.",
      "estimated_savings": "Frees 875m of allocatable node CPU (87.5% reduction in request)",
      "review_status": "pending",
      "created_at": "2026-10-28T22:00:00Z",
      "updated_at": "2026-10-28T22:15:00Z"
    }
  ],
  "error": null,
  "timestamp": "2026-10-28T22:15:05Z"
}
```

---

### 2.2 Retrieve Recommendation Details

`GET /api/v1/recommendations/{recommendation_id}`  
`GET /api/recommendations/{recommendation_id}`

Returns the full recommendation record matching `recommendation_id`.

#### Status Codes
* `200 OK`: Recommendation found.
* `404 Not Found`: Recommendation with specified ID does not exist.

---

### 2.3 Update Recommendation Review Status

`PATCH /api/v1/recommendations/{recommendation_id}`  
`POST /api/v1/recommendations/{recommendation_id}/status`

Updates the human review status of a recommendation to `applied` or `dismissed`.

#### Request Body

```json
{
  "review_status": "applied"
}
```

#### Status Codes
* `200 OK`: Recommendation status updated.
* `400 Bad Request`: Invalid review status provided.
* `404 Not Found`: Recommendation not found.

---

### 2.4 Trigger On-Demand Recommendation Evaluation

`POST /api/v1/recommendations/evaluate`  
`POST /api/recommendations/evaluate`

Triggers an immediate evaluation sweep of live Kubernetes workloads and Prometheus telemetry.

#### Example Response

```json
{
  "status": "ok",
  "data": {
    "created": 1,
    "updated": 2,
    "unchanged": 0,
    "total_candidates": 3
  },
  "error": null,
  "timestamp": "2026-10-28T22:15:10Z"
}
```
