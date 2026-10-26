/**
 * TanStack Query hooks for KubeWatch server state.
 */

import { useQuery } from '@tanstack/react-query';
import { apiClient } from './client';

export type TimeRangeOption = '1h' | '6h' | '24h' | '7d';

export function calculateTimeRange(range: TimeRangeOption): { start: string; end: string; step: number } {
  const now = new Date();
  const end = now.toISOString();

  let deltaMs = 3600 * 1000;
  let step = 30; // 30s

  if (range === '6h') {
    deltaMs = 6 * 3600 * 1000;
    step = 60; // 1m
  } else if (range === '24h') {
    deltaMs = 24 * 3600 * 1000;
    step = 300; // 5m
  } else if (range === '7d') {
    deltaMs = 7 * 24 * 3600 * 1000;
    step = 1800; // 30m
  }

  const start = new Date(now.getTime() - deltaMs).toISOString();
  return { start, end, step };
}

export const queryKeys = {
  health: ['health'] as const,
  overview: ['cluster', 'overview'] as const,
  nodes: ['nodes'] as const,
  pods: (namespace?: string) => ['pods', namespace || 'all'] as const,
  deployments: (namespace?: string) => ['deployments', namespace || 'all'] as const,
  nodeCpu: (range: TimeRangeOption) => ['metrics', 'cpu', 'nodes', range] as const,
  podCpu: (namespace?: string, pod?: string, range?: TimeRangeOption) =>
    ['metrics', 'cpu', 'pods', namespace || 'all', pod || 'all', range || '1h'] as const,
  nodeMemory: (range: TimeRangeOption) => ['metrics', 'memory', 'nodes', range] as const,
  podMemory: (namespace?: string, pod?: string, range?: TimeRangeOption) =>
    ['metrics', 'memory', 'pods', namespace || 'all', pod || 'all', range || '1h'] as const,
  incidents: ['incidents'] as const,
  recommendations: ['recommendations'] as const,
};

export function useHealth(refetchInterval: number = 10000) {
  return useQuery({
    queryKey: queryKeys.health,
    queryFn: apiClient.getHealth,
    refetchInterval,
    retry: 1,
  });
}

export function useClusterOverview(refetchInterval: number = 15000) {
  return useQuery({
    queryKey: queryKeys.overview,
    queryFn: apiClient.getClusterOverview,
    refetchInterval,
  });
}

export function useNodes(refetchInterval: number = 15000) {
  return useQuery({
    queryKey: queryKeys.nodes,
    queryFn: apiClient.getNodes,
    refetchInterval,
  });
}

export function usePods(namespace?: string, refetchInterval: number = 15000) {
  return useQuery({
    queryKey: queryKeys.pods(namespace),
    queryFn: () => apiClient.getPods(namespace),
    refetchInterval,
  });
}

export function useDeployments(namespace?: string, refetchInterval: number = 15000) {
  return useQuery({
    queryKey: queryKeys.deployments(namespace),
    queryFn: () => apiClient.getDeployments(namespace),
    refetchInterval,
  });
}

export function useNodeCpuMetrics(range: TimeRangeOption = '1h', refetchInterval: number = 30000) {
  return useQuery({
    queryKey: queryKeys.nodeCpu(range),
    queryFn: () => {
      const { start, end, step } = calculateTimeRange(range);
      return apiClient.getNodeCpuMetrics({ start, end, step });
    },
    refetchInterval,
  });
}

export function usePodCpuMetrics(
  namespace?: string,
  pod?: string,
  range: TimeRangeOption = '1h',
  refetchInterval: number = 30000,
) {
  return useQuery({
    queryKey: queryKeys.podCpu(namespace, pod, range),
    queryFn: () => {
      const { start, end, step } = calculateTimeRange(range);
      return apiClient.getPodCpuMetrics({ namespace, pod, start, end, step });
    },
    refetchInterval,
  });
}

export function useNodeMemoryMetrics(range: TimeRangeOption = '1h', refetchInterval: number = 30000) {
  return useQuery({
    queryKey: queryKeys.nodeMemory(range),
    queryFn: () => {
      const { start, end, step } = calculateTimeRange(range);
      return apiClient.getNodeMemoryMetrics({ start, end, step });
    },
    refetchInterval,
  });
}

export function usePodMemoryMetrics(
  namespace?: string,
  pod?: string,
  range: TimeRangeOption = '1h',
  refetchInterval: number = 30000,
) {
  return useQuery({
    queryKey: queryKeys.podMemory(namespace, pod, range),
    queryFn: () => {
      const { start, end, step } = calculateTimeRange(range);
      return apiClient.getPodMemoryMetrics({ namespace, pod, start, end, step });
    },
    refetchInterval,
  });
}

export function useIncidents() {
  return useQuery({
    queryKey: queryKeys.incidents,
    queryFn: apiClient.getIncidents,
    retry: false, // Don't spam retries if endpoint is 404
  });
}

export function useRecommendations() {
  return useQuery({
    queryKey: queryKeys.recommendations,
    queryFn: apiClient.getRecommendations,
    retry: false, // Don't spam retries if endpoint is 404
  });
}
