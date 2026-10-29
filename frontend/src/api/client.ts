/**
 * Typed HTTP API client for KubeWatch backend.
 */

import type {
  ApiResponse,
  ClusterOverview,
  DeploymentInfo,
  HealthData,
  IncidentInfo,
  MetricsResult,
  NodeInfo,
  PodInfo,
  RecommendationInfo,
} from './types';

export class ApiClientError extends Error {
  public status?: number;
  public endpoint: string;
  public isNotImplemented: boolean;

  constructor(message: string, endpoint: string, status?: number) {
    super(message);
    this.name = 'ApiClientError';
    this.endpoint = endpoint;
    this.status = status;
    this.isNotImplemented = status === 404 || status === 501;
  }
}

const RAW_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
// Remove any trailing slash
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, '');

async function fetchJson<T>(endpoint: string, searchParams?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${API_BASE_URL}${endpoint}`);

  if (searchParams) {
    Object.entries(searchParams).forEach(([key, val]) => {
      if (val !== undefined && val !== null && val !== '') {
        url.searchParams.append(key, String(val));
      }
    });
  }

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method: 'GET',
      headers: {
        Accept: 'application/json',
      },
    });
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Network request failed';
    throw new ApiClientError(
      `Cannot connect to KubeWatch backend at ${API_BASE_URL}: ${message}`,
      endpoint,
    );
  }

  if (response.status === 404 || response.status === 501) {
    throw new ApiClientError(
      `Backend endpoint ${endpoint} is not implemented yet.`,
      endpoint,
      response.status,
    );
  }

  if (!response.ok) {
    let errorDetail = `HTTP ${response.status} ${response.statusText}`;
    try {
      const errBody = await response.json();
      if (errBody) {
        if (typeof errBody.error === 'string') {
          errorDetail = errBody.error;
        } else if (typeof errBody.detail === 'string') {
          errorDetail = errBody.detail;
        } else if (errBody.detail && typeof errBody.detail === 'object') {
          errorDetail = JSON.stringify(errBody.detail);
        }
      }
    } catch {
      // Body not JSON
    }
    throw new ApiClientError(errorDetail, endpoint, response.status);
  }

  const envelope: ApiResponse<T> = await response.json();

  if (envelope.status === 'error') {
    throw new ApiClientError(
      envelope.error || 'Server returned an error status without details',
      endpoint,
      response.status,
    );
  }

  if (envelope.data === null || envelope.data === undefined) {
    throw new ApiClientError('Response payload was unexpectedly null', endpoint, response.status);
  }

  return envelope.data;
}

export const apiClient = {
  getHealth: () => fetchJson<HealthData>('/api/health'),

  getClusterOverview: () => fetchJson<ClusterOverview>('/api/cluster/overview'),

  getNodes: () => fetchJson<NodeInfo[]>('/api/nodes'),

  getPods: (namespace?: string) =>
    fetchJson<PodInfo[]>('/api/pods', { namespace }),

  getDeployments: (namespace?: string) =>
    fetchJson<DeploymentInfo[]>('/api/deployments', { namespace }),

  getNodeCpuMetrics: (params?: { start?: string; end?: string; step?: number }) =>
    fetchJson<MetricsResult>('/api/metrics/cpu/nodes', params),

  getPodCpuMetrics: (params?: { namespace?: string; pod?: string; start?: string; end?: string; step?: number }) =>
    fetchJson<MetricsResult>('/api/metrics/cpu/pods', params),

  getNodeMemoryMetrics: (params?: { start?: string; end?: string; step?: number }) =>
    fetchJson<MetricsResult>('/api/metrics/memory/nodes', params),

  getPodMemoryMetrics: (params?: { namespace?: string; pod?: string; start?: string; end?: string; step?: number }) =>
    fetchJson<MetricsResult>('/api/metrics/memory/pods', params),

  getIncidents: () => fetchJson<IncidentInfo[]>('/api/incidents'),

  getRecommendations: () => fetchJson<RecommendationInfo[]>('/api/recommendations'),
};
