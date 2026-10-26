import React from 'react';
import {
  Server,
  Boxes,
  Layers,
  Cpu,
  Database,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  HardDrive,
} from 'lucide-react';
import { MetricCard } from '../components/common/MetricCard';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import type { ClusterOverview, NodeInfo, PodInfo, DeploymentInfo, HealthData } from '../api/types';

interface OverviewPageProps {
  overview?: ClusterOverview | null;
  nodes?: NodeInfo[] | null;
  pods?: PodInfo[] | null;
  deployments?: DeploymentInfo[] | null;
  health?: HealthData | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  onNavigateTab: (tab: 'workloads' | 'performance' | 'incidents' | 'recommendations') => void;
  onRetry: () => void;
}

export const OverviewPage: React.FC<OverviewPageProps> = ({
  overview,
  nodes,
  pods,
  deployments,
  health,
  isLoading,
  isError,
  error,
  onNavigateTab,
  onRetry,
}) => {
  if (isLoading && !overview) {
    return <LoadingState message="Connecting to cluster and loading overview..." height="320px" />;
  }

  if (isError && !overview) {
    return (
      <ErrorState
        title="Failed to Load Cluster Overview"
        message={error?.message || 'Unable to retrieve cluster summary data.'}
        onRetry={onRetry}
      />
    );
  }

  // Derive pod phase stats
  const podStats = {
    running: 0,
    pending: 0,
    failed: 0,
    succeeded: 0,
    unknown: 0,
    totalRestarts: 0,
  };

  if (pods) {
    pods.forEach((p) => {
      const ph = p.phase.toLowerCase();
      if (ph === 'running') podStats.running++;
      else if (ph === 'pending') podStats.pending++;
      else if (ph === 'failed') podStats.failed++;
      else if (ph === 'succeeded') podStats.succeeded++;
      else podStats.unknown++;

      podStats.totalRestarts += p.restart_count || 0;
    });
  }

  // Derive deployment availability stats
  const deploymentStats = {
    total: deployments?.length ?? overview?.deployment_count ?? 0,
    availableReplicas: 0,
    unavailableReplicas: 0,
    desiredReplicas: 0,
  };

  if (deployments) {
    deployments.forEach((d) => {
      deploymentStats.availableReplicas += d.available_replicas || 0;
      deploymentStats.unavailableReplicas += d.unavailable_replicas || 0;
      deploymentStats.desiredReplicas += d.replicas || 0;
    });
  }

  // Node ready counts
  const readyNodesCount = nodes?.filter((n) => n.status.toLowerCase() === 'ready').length ?? 0;
  const totalNodesCount = nodes?.length ?? overview?.node_count ?? 0;

  const promHealthy = health?.components.find((c) => c.name.toLowerCase() === 'prometheus')?.healthy ?? false;

  return (
    <div className="page-content" id="panel-overview" role="tabpanel" aria-labelledby="tab-overview">
      {/* Top operational metric cards */}
      <section className="section-block">
        <div className="section-header">
          <div>
            <h2 className="section-title">Cluster Summary</h2>
            <p className="section-subtitle">Real-time state aggregated across active nodes and workloads</p>
          </div>
        </div>

        <div className="grid-cards grid-cards--4">
          <MetricCard
            title="Nodes"
            value={totalNodesCount}
            subtitle={totalNodesCount > 0 ? `${readyNodesCount} of ${totalNodesCount} Ready` : 'No nodes discovered'}
            icon={Server}
            badge={
              totalNodesCount > 0 ? (
                <StatusBadge status={readyNodesCount === totalNodesCount ? 'Ready' : 'Degraded'} />
              ) : undefined
            }
          />

          <MetricCard
            title="Workload Pods"
            value={overview?.pod_count ?? (pods ? pods.length : null)}
            subtitle={
              pods
                ? `${podStats.running} running, ${podStats.pending} pending, ${podStats.failed} failed`
                : 'Across all namespaces'
            }
            icon={Boxes}
            badge={
              podStats.failed > 0 ? (
                <StatusBadge status={`${podStats.failed} Failed`} variant="error" />
              ) : podStats.pending > 0 ? (
                <StatusBadge status={`${podStats.pending} Pending`} variant="warning" />
              ) : (
                <StatusBadge status="Healthy" variant="success" />
              )
            }
          />

          <MetricCard
            title="Deployments"
            value={deploymentStats.total}
            subtitle={
              deploymentStats.unavailableReplicas > 0
                ? `${deploymentStats.unavailableReplicas} replicas unavailable`
                : 'All replicas healthy'
            }
            icon={Layers}
            badge={
              deploymentStats.unavailableReplicas > 0 ? (
                <StatusBadge status="Degraded" variant="error" />
              ) : (
                <StatusBadge status="Available" variant="success" />
              )
            }
          />

          <MetricCard
            title="Namespaces"
            value={overview?.namespace_count ?? null}
            subtitle="Configured tenant namespaces"
            icon={HardDrive}
          />
        </div>
      </section>

      {/* Utilization & Performance Summary */}
      <section className="section-block">
        <div className="section-header">
          <div>
            <h2 className="section-title">Resource Utilization</h2>
            <p className="section-subtitle">
              Live cluster capacity and utilization computed via Prometheus
            </p>
          </div>
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            onClick={() => onNavigateTab('performance')}
          >
            <span>View Timeseries</span>
            <ArrowRight size={14} className="icon-ml" />
          </button>
        </div>

        <div className="grid-cards grid-cards--2">
          <MetricCard
            title="Cluster CPU Usage"
            value={overview?.cpu_usage_percent !== null && overview?.cpu_usage_percent !== undefined ? overview.cpu_usage_percent : null}
            unit="%"
            subtitle={
              overview?.cpu_capacity
                ? `Total Capacity: ${overview.cpu_capacity}`
                : undefined
            }
            icon={Cpu}
            isUnavailable={!promHealthy || overview?.cpu_usage_percent === null || overview?.cpu_usage_percent === undefined}
            unavailableReason={
              !promHealthy
                ? 'Prometheus metrics offline (port-forward 9090)'
                : 'Query returning no metric series'
            }
          />

          <MetricCard
            title="Cluster Memory Usage"
            value={overview?.memory_usage_percent !== null && overview?.memory_usage_percent !== undefined ? overview.memory_usage_percent : null}
            unit="%"
            subtitle={
              overview?.memory_capacity
                ? `Total Capacity: ${(Number(overview.memory_capacity) / (1024 * 1024 * 1024)).toFixed(1)} GiB`
                : undefined
            }
            icon={Database}
            isUnavailable={!promHealthy || overview?.memory_usage_percent === null || overview?.memory_usage_percent === undefined}
            unavailableReason={
              !promHealthy
                ? 'Prometheus metrics offline (port-forward 9090)'
                : 'Query returning no metric series'
            }
          />
        </div>
      </section>

      {/* Nodes & Pod Health Breakdown Grid */}
      <div className="grid-split">
        {/* Nodes summary card */}
        <div className="card">
          <div className="card__header">
            <h3 className="card__title">Cluster Nodes</h3>
            <span className="badge-count">{nodes?.length || 0}</span>
          </div>
          <div className="card__body p-0">
            {nodes && nodes.length > 0 ? (
              <div className="table-responsive">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Node Name</th>
                      <th>Status</th>
                      <th>Roles</th>
                      <th>CPU Allocatable</th>
                      <th>Memory Allocatable</th>
                    </tr>
                  </thead>
                  <tbody>
                    {nodes.map((node) => (
                      <tr key={node.name}>
                        <td className="font-mono font-medium">{node.name}</td>
                        <td>
                          <StatusBadge status={node.status} />
                        </td>
                        <td>
                          {node.roles.length > 0
                            ? node.roles.join(', ')
                            : '<worker>'}
                        </td>
                        <td className="font-mono">{node.allocatable.cpu || '—'}</td>
                        <td className="font-mono">{node.allocatable.memory || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="p-4 text-center text-muted">No nodes found</div>
            )}
          </div>
        </div>

        {/* Operational Highlights Card */}
        <div className="card">
          <div className="card__header">
            <h3 className="card__title">Operational Status</h3>
            <span className="app-header__tag">Live Rules</span>
          </div>
          <div className="card__body">
            <div className="status-checklist">
              <div className="status-checklist__item">
                <div className="status-checklist__icon status-checklist__icon--ok">
                  <CheckCircle2 size={16} />
                </div>
                <div className="status-checklist__info">
                  <span className="status-checklist__label">Kubernetes API Connection</span>
                  <span className="status-checklist__desc">Direct host communication with active cluster</span>
                </div>
                <StatusBadge status="Connected" variant="success" />
              </div>

              <div className="status-checklist__item">
                <div
                  className={`status-checklist__icon ${
                    promHealthy ? 'status-checklist__icon--ok' : 'status-checklist__icon--warning'
                  }`}
                >
                  {promHealthy ? <CheckCircle2 size={16} /> : <AlertTriangle size={16} />}
                </div>
                <div className="status-checklist__info">
                  <span className="status-checklist__label">Prometheus Metric Collector</span>
                  <span className="status-checklist__desc">
                    {promHealthy
                      ? 'node-exporter & cAdvisor streams active'
                      : 'Metrics collection offline (requires port-forward on :9090)'}
                  </span>
                </div>
                <StatusBadge status={promHealthy ? 'Live' : 'Offline'} variant={promHealthy ? 'success' : 'warning'} />
              </div>

              <div className="status-checklist__item">
                <div className="status-checklist__icon status-checklist__icon--info">
                  <ShieldCheck size={16} />
                </div>
                <div className="status-checklist__info">
                  <span className="status-checklist__label">Incident Detection Engine</span>
                  <span className="status-checklist__desc">Diagnostic rules pipeline (Phase 2)</span>
                </div>
                <StatusBadge status="Standby" variant="neutral" />
              </div>
            </div>

            <div className="card-callout mt-4">
              <span className="card-callout__title">Workload Health Notice:</span>
              <span className="card-callout__text">
                {podStats.failed > 0
                  ? `${podStats.failed} pod(s) are in Failed state. Inspect the Workloads tab for details.`
                  : podStats.totalRestarts > 5
                  ? `High restart activity detected (${podStats.totalRestarts} total restarts across pods).`
                  : 'All monitored workloads are operating within expected parameters.'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};
