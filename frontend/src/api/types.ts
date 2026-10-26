/**
 * KubeWatch API TypeScript definitions matching backend Pydantic schemas.
 */

export interface ApiResponse<T> {
  status: 'ok' | 'error' | 'degraded';
  data: T | null;
  error?: string | null;
  timestamp: string;
}

export interface ComponentHealth {
  name: string;
  healthy: boolean;
  message?: string | null;
}

export interface HealthData {
  healthy: boolean;
  components: ComponentHealth[];
}

export interface NodeCondition {
  type: string;
  status: string;
  reason?: string | null;
  message?: string | null;
}

export interface NodeResources {
  cpu?: string | null;
  memory?: string | null;
}

export interface NodeInfo {
  name: string;
  status: 'Ready' | 'NotReady' | 'Unknown' | string;
  roles: string[];
  capacity: NodeResources;
  allocatable: NodeResources;
  conditions: NodeCondition[];
  created_at?: string | null;
}

export interface ContainerResources {
  cpu_request?: string | null;
  cpu_limit?: string | null;
  memory_request?: string | null;
  memory_limit?: string | null;
}

export interface ContainerInfo {
  name: string;
  image: string;
  ready: boolean;
  restart_count: number;
  state?: string | null;
  resources: ContainerResources;
}

export interface PodInfo {
  name: string;
  namespace: string;
  phase: 'Running' | 'Pending' | 'Succeeded' | 'Failed' | 'Unknown' | string;
  node_name?: string | null;
  restart_count: number;
  containers: ContainerInfo[];
  created_at?: string | null;
}

export interface DeploymentCondition {
  type: string;
  status: string;
  reason?: string | null;
  message?: string | null;
}

export interface DeploymentInfo {
  name: string;
  namespace: string;
  replicas: number;
  ready_replicas: number;
  available_replicas: number;
  unavailable_replicas: number;
  strategy?: string | null;
  conditions: DeploymentCondition[];
  created_at?: string | null;
}

export interface ClusterOverview {
  node_count: number;
  pod_count: number;
  namespace_count: number;
  deployment_count: number;
  cpu_capacity?: string | null;
  memory_capacity?: string | null;
  cpu_usage_percent?: number | null;
  memory_usage_percent?: number | null;
}

export interface MetricDataPoint {
  timestamp: number;
  value: number;
}

export interface MetricSeries {
  metric_labels: Record<string, string>;
  values: MetricDataPoint[];
}

export interface MetricsResult {
  query_name: string;
  series: MetricSeries[];
  error?: string | null;
}

export interface IncidentInfo {
  id: string;
  rule_name: string;
  severity: 'critical' | 'warning' | 'info';
  resource_type: string;
  resource_name: string;
  namespace?: string | null;
  message: string;
  observed_at: string;
  status: 'active' | 'resolved';
}

export interface RecommendationInfo {
  id: string;
  workload_name: string;
  namespace: string;
  resource_type: string;
  current_spec: Record<string, string>;
  recommended_spec: Record<string, string>;
  reasoning: string;
  estimated_savings?: string | null;
  status: 'open' | 'applied' | 'dismissed';
}
