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

