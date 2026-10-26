import React, { useState, useMemo } from 'react';
import { Search, Filter, Boxes, Layers, ChevronDown, ChevronRight } from 'lucide-react';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import type { PodInfo, DeploymentInfo } from '../api/types';

interface WorkloadsPageProps {
  pods?: PodInfo[] | null;
  deployments?: DeploymentInfo[] | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  selectedNamespace: string;
  onNamespaceChange: (ns: string) => void;
  onRetry: () => void;
}

export const WorkloadsPage: React.FC<WorkloadsPageProps> = ({
  pods,
  deployments,
  isLoading,
  isError,
  error,
  selectedNamespace,
  onNamespaceChange,
  onRetry,
}) => {
  const [activeSubTab, setActiveSubTab] = useState<'pods' | 'deployments'>('pods');
  const [searchQuery, setSearchQuery] = useState('');
  const [phaseFilter, setPhaseFilter] = useState<string>('all');
  const [expandedPod, setExpandedPod] = useState<string | null>(null);

  // Derive unique namespaces list from existing pods and deployments
  const namespaces = useMemo(() => {
    const set = new Set<string>();
    pods?.forEach((p) => p.namespace && set.add(p.namespace));
    deployments?.forEach((d) => d.namespace && set.add(d.namespace));
    return Array.from(set).sort();
  }, [pods, deployments]);

  // Filter pods
  const filteredPods = useMemo(() => {
    if (!pods) return [];
    return pods.filter((p) => {
      const matchNamespace = !selectedNamespace || p.namespace === selectedNamespace;
      const matchSearch =
        !searchQuery ||
        p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        p.namespace.toLowerCase().includes(searchQuery.toLowerCase());
      const matchPhase = phaseFilter === 'all' || p.phase.toLowerCase() === phaseFilter.toLowerCase();
      return matchNamespace && matchSearch && matchPhase;
    });
  }, [pods, selectedNamespace, searchQuery, phaseFilter]);

  // Filter deployments
  const filteredDeployments = useMemo(() => {
    if (!deployments) return [];
    return deployments.filter((d) => {
      const matchNamespace = !selectedNamespace || d.namespace === selectedNamespace;
      const matchSearch =
        !searchQuery ||
        d.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        d.namespace.toLowerCase().includes(searchQuery.toLowerCase());
      return matchNamespace && matchSearch;
    });
  }, [deployments, selectedNamespace, searchQuery]);

  if (isLoading && !pods && !deployments) {
    return <LoadingState message="Loading Kubernetes workloads and container specifications..." height="300px" />;
  }

  if (isError && !pods && !deployments) {
    return (
      <ErrorState
        title="Failed to Load Workloads"
        message={error?.message || 'Unable to retrieve pods and deployments from the cluster.'}
        onRetry={onRetry}
      />
    );
  }

  return (
    <div className="page-content" id="panel-workloads" role="tabpanel" aria-labelledby="tab-workloads">
      {/* Controls Bar */}
      <div className="controls-bar">
        <div className="controls-bar__left">
          {/* Sub-tabs: Pods vs Deployments */}
          <div className="segmented-control" role="group" aria-label="Workload Type">
            <button
              type="button"
              className={`segmented-control__btn ${activeSubTab === 'pods' ? 'segmented-control__btn--active' : ''}`}
              onClick={() => setActiveSubTab('pods')}
            >
              <Boxes size={14} className="icon-mr" />
              <span>Pods</span>
              <span className="badge-count ml-1">{filteredPods.length}</span>
            </button>
            <button
              type="button"
              className={`segmented-control__btn ${activeSubTab === 'deployments' ? 'segmented-control__btn--active' : ''}`}
              onClick={() => setActiveSubTab('deployments')}
            >
              <Layers size={14} className="icon-mr" />
              <span>Deployments</span>
              <span className="badge-count ml-1">{filteredDeployments.length}</span>
            </button>
          </div>

          {/* Search box */}
          <div className="search-input-wrapper">
            <Search size={14} className="search-input-icon" />
            <input
              type="text"
              className="input search-input"
              placeholder="Filter by name..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Filter workloads by name"
            />
            {searchQuery && (
              <button
                type="button"
                className="search-input-clear"
                onClick={() => setSearchQuery('')}
                title="Clear search"
              >
                &times;
              </button>
            )}
          </div>
        </div>

        <div className="controls-bar__right">
          {/* Namespace Filter */}
          <div className="filter-group">
            <label htmlFor="namespace-select" className="filter-label">
              <Filter size={13} className="icon-mr" />
              Namespace:
            </label>
            <select
              id="namespace-select"
              className="select select--sm font-mono"
              value={selectedNamespace}
              onChange={(e) => onNamespaceChange(e.target.value)}
            >
              <option value="">All Namespaces</option>
              {namespaces.map((ns) => (
                <option key={ns} value={ns}>
                  {ns}
                </option>
              ))}
            </select>
          </div>

          {/* Pod Phase Filter (only shown on pods sub-tab) */}
          {activeSubTab === 'pods' && (
            <div className="filter-group">
              <label htmlFor="phase-select" className="filter-label">
                Phase:
              </label>
              <select
                id="phase-select"
                className="select select--sm"
                value={phaseFilter}
                onChange={(e) => setPhaseFilter(e.target.value)}
              >
                <option value="all">All Phases</option>
                <option value="running">Running</option>
                <option value="pending">Pending</option>
                <option value="failed">Failed</option>
                <option value="succeeded">Succeeded</option>
              </select>
            </div>
          )}
        </div>
      </div>

      {/* Main Table Content */}
      <div className="card">
        {activeSubTab === 'pods' ? (
          filteredPods.length > 0 ? (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: '32px' }} />
                    <th>Pod Name</th>
                    <th>Namespace</th>
                    <th>Phase</th>
                    <th>Node</th>
                    <th>Restarts</th>
                    <th>Containers</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredPods.map((pod) => {
                    const isExpanded = expandedPod === pod.name;
                    const hasHighRestarts = pod.restart_count > 3;

                    return (
                      <React.Fragment key={`${pod.namespace}/${pod.name}`}>
                        <tr
                          className={`table-row-clickable ${isExpanded ? 'table-row--expanded' : ''}`}
                          onClick={() => setExpandedPod(isExpanded ? null : pod.name)}
                        >
                          <td className="text-center text-muted">
                            {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </td>
                          <td className="font-mono font-medium text-primary">
                            {pod.name}
                          </td>
                          <td>
                            <span className="namespace-pill">{pod.namespace}</span>
                          </td>
                          <td>
                            <StatusBadge status={pod.phase} />
                          </td>
                          <td className="font-mono text-muted">{pod.node_name || '—'}</td>
                          <td>
                            <span
                              className={`restart-badge ${
                                hasHighRestarts ? 'restart-badge--alert' : 'restart-badge--normal'
                              }`}
                            >
                              {pod.restart_count}
                            </span>
                          </td>
                          <td>
                            <span className="text-muted">
                              {pod.containers.filter((c) => c.ready).length}/{pod.containers.length} Ready
                            </span>
                          </td>
                          <td className="text-muted text-sm font-mono">
                            {pod.created_at ? new Date(pod.created_at).toLocaleDateString() : '—'}
                          </td>
                        </tr>

                        {/* Expanded details for containers */}
                        {isExpanded && (
                          <tr className="table-row-detail">
                            <td colSpan={8}>
                              <div className="container-details">
                                <h5 className="container-details__title">Container Specifications</h5>
                                <div className="container-details__grid">
                                  {pod.containers.map((c) => (
                                    <div key={c.name} className="container-card">
                                      <div className="container-card__header">
                                        <span className="container-card__name">{c.name}</span>
                                        <StatusBadge status={c.ready ? 'Ready' : 'Not Ready'} />
                                      </div>
                                      <div className="container-card__image" title={c.image}>
                                        <span className="text-muted">Image:</span> {c.image}
                                      </div>
                                      <div className="container-card__resources">
                                        <div className="resource-item">
                                          <span className="resource-label">CPU Req:</span>
                                          <span className="resource-val font-mono">{c.resources.cpu_request || 'None'}</span>
                                        </div>
                                        <div className="resource-item">
                                          <span className="resource-label">CPU Limit:</span>
                                          <span className="resource-val font-mono">{c.resources.cpu_limit || 'None'}</span>
                                        </div>
                                        <div className="resource-item">
                                          <span className="resource-label">Mem Req:</span>
                                          <span className="resource-val font-mono">{c.resources.memory_request || 'None'}</span>
                                        </div>
                                        <div className="resource-item">
                                          <span className="resource-label">Mem Limit:</span>
                                          <span className="resource-val font-mono">{c.resources.memory_limit || 'None'}</span>
                                        </div>
                                      </div>
                                      {c.state && (
                                        <div className="container-card__state">
                                          <span className="text-muted">State:</span> {c.state}
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={Boxes}
              title="No Pods Found"
              description={
                searchQuery || selectedNamespace || phaseFilter !== 'all'
                  ? 'No pods matched the selected namespace, search query, or phase filter.'
                  : 'No pods are currently deployed in the connected cluster.'
              }
            />
          )
        ) : (
          /* Deployments Tab */
          filteredDeployments.length > 0 ? (
            <div className="table-responsive">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Deployment Name</th>
                    <th>Namespace</th>
                    <th>Status</th>
                    <th>Replicas</th>
                    <th>Available</th>
                    <th>Unavailable</th>
                    <th>Strategy</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredDeployments.map((dep) => {
                    const isHealthy = dep.unavailable_replicas === 0 && dep.ready_replicas >= dep.replicas;

                    return (
                      <tr key={`${dep.namespace}/${dep.name}`}>
                        <td className="font-mono font-medium text-primary">{dep.name}</td>
                        <td>
                          <span className="namespace-pill">{dep.namespace}</span>
                        </td>
                        <td>
                          <StatusBadge status={isHealthy ? 'Available' : 'Degraded'} />
                        </td>
                        <td className="font-mono">{dep.replicas}</td>
                        <td className="font-mono text-success">{dep.available_replicas}</td>
                        <td className="font-mono text-danger">{dep.unavailable_replicas}</td>
                        <td>{dep.strategy || 'RollingUpdate'}</td>
                        <td className="text-muted text-sm font-mono">
                          {dep.created_at ? new Date(dep.created_at).toLocaleDateString() : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState
              icon={Layers}
              title="No Deployments Found"
              description={
                searchQuery || selectedNamespace
                  ? 'No deployments match the selected namespace or search query.'
                  : 'No deployments are currently running in the connected cluster.'
              }
            />
          )
        )}
      </div>
    </div>
  );
};
