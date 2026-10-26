import React from 'react';
import { AlertTriangle, ShieldAlert, CheckCircle, Info, RefreshCw } from 'lucide-react';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingState } from '../components/common/LoadingState';
import { EmptyState } from '../components/common/EmptyState';
import type { IncidentInfo } from '../api/types';
import { ApiClientError } from '../api/client';

interface IncidentsPageProps {
  incidents?: IncidentInfo[] | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  onRetry: () => void;
}

export const IncidentsPage: React.FC<IncidentsPageProps> = ({
  incidents,
  isLoading,
  isError,
  error,
  onRetry,
}) => {
  const isNotImplemented =
    isError && error instanceof ApiClientError && error.isNotImplemented;

  if (isLoading && !incidents) {
    return <LoadingState message="Checking cluster incident logs..." height="300px" />;
  }

  return (
    <div className="page-content" id="panel-incidents" role="tabpanel" aria-labelledby="tab-incidents">
      <div className="section-header">
        <div>
          <h2 className="section-title">Operational Incidents</h2>
          <p className="section-subtitle">
            Rule-based cluster problem detection backed by deterministic Kubernetes and Prometheus evidence
          </p>
        </div>
        <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
          <RefreshCw size={13} className="icon-mr" />
          <span>Refresh</span>
        </button>
      </div>

      {isNotImplemented ? (
        <div className="card p-6">
          <div className="unimplemented-state">
            <div className="unimplemented-state__icon unimplemented-state__icon--info">
              <ShieldAlert size={36} />
            </div>
            <h3 className="unimplemented-state__title">Diagnostic Engine Scheduled for Phase 2</h3>
            <p className="unimplemented-state__description">
              The backend diagnostic pipeline endpoint (<code>/api/incidents</code>) is currently under development as part of Phase 2 of KubeWatch.
            </p>
            <div className="unimplemented-state__details">
              <h4>Planned Diagnostic Rules:</h4>
              <ul>
                <li><strong>Restart Loop Rule:</strong> Detects CrashLoopBackOff via container restart counts and termination states.</li>
                <li><strong>Pending Pod Rule:</strong> Correlates unschedulable pod conditions with node resource capacities.</li>
                <li><strong>Deployment Availability Rule:</strong> Alerts when unavailable replicas exceed zero for sustained intervals.</li>
                <li><strong>Resource Pressure Rule:</strong> Detects sustained node CPU &gt;85% or Memory &gt;90%.</li>
              </ul>
            </div>
            <div className="card-note mt-4">
              <Info size={15} className="card-note__icon" />
              <span className="card-note__text">
                <strong>Data Integrity Notice:</strong> In adherence to KubeWatch design principles, fake incidents or fabricated sample alerts are strictly never displayed.
              </span>
            </div>
          </div>
        </div>
      ) : isError ? (
        <div className="card p-6">
          <EmptyState
            icon={AlertTriangle}
            title="Unable to Retrieve Incidents"
            description={error?.message || 'Error occurred communicating with the incident diagnostic API.'}
            action={
              <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
                Retry
              </button>
            }
          />
        </div>
      ) : incidents && incidents.length > 0 ? (
        <div className="card">
          <div className="table-responsive">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Severity</th>
                  <th>Rule Name</th>
                  <th>Resource</th>
                  <th>Namespace</th>
                  <th>Message & Evidence</th>
                  <th>Observed At</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {incidents.map((inc) => (
                  <tr key={inc.id}>
                    <td>
                      <StatusBadge
                        status={inc.severity.toUpperCase()}
                        variant={inc.severity === 'critical' ? 'error' : inc.severity === 'warning' ? 'warning' : 'info'}
                      />
                    </td>
                    <td className="font-mono text-sm">{inc.rule_name}</td>
                    <td className="font-mono font-medium text-primary">
                      {inc.resource_type}/{inc.resource_name}
                    </td>
                    <td>{inc.namespace || '—'}</td>
                    <td>{inc.message}</td>
                    <td className="text-muted text-sm font-mono">
                      {new Date(inc.observed_at).toLocaleString()}
                    </td>
                    <td>
                      <StatusBadge status={inc.status} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="card">
          <EmptyState
            icon={CheckCircle}
            title="No Active Incidents"
            description="The diagnostic engine has reported zero operational alerts. All workloads and cluster nodes are operating normally."
          />
        </div>
      )}
    </div>
  );
};
