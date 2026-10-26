import React from 'react';
import { Lightbulb, Sparkles, CheckCircle, Info, RefreshCw, AlertTriangle } from 'lucide-react';
import { StatusBadge } from '../components/common/StatusBadge';
import { LoadingState } from '../components/common/LoadingState';
import { EmptyState } from '../components/common/EmptyState';
import type { RecommendationInfo } from '../api/types';
import { ApiClientError } from '../api/client';

interface RecommendationsPageProps {
  recommendations?: RecommendationInfo[] | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  onRetry: () => void;
}

export const RecommendationsPage: React.FC<RecommendationsPageProps> = ({
  recommendations,
  isLoading,
  isError,
  error,
  onRetry,
}) => {
  const isNotImplemented =
    isError && error instanceof ApiClientError && error.isNotImplemented;

  if (isLoading && !recommendations) {
    return <LoadingState message="Evaluating workload right-sizing metrics..." height="300px" />;
  }

  return (
    <div className="page-content" id="panel-recommendations" role="tabpanel" aria-labelledby="tab-recommendations">
      <div className="section-header">
        <div>
          <h2 className="section-title">Resource Right-Sizing Recommendations</h2>
          <p className="section-subtitle">
            Explainable container optimization recommendations based on percentile utilization history
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
            <div className="unimplemented-state__icon unimplemented-state__icon--purple">
              <Sparkles size={36} />
            </div>
            <h3 className="unimplemented-state__title">Recommendation Engine Scheduled for Phase 3</h3>
            <p className="unimplemented-state__description">
              The resource right-sizing engine endpoint (<code>/api/recommendations</code>) will be introduced in Phase 3.
              It will compute explainable CPU and memory recommendations using configurable percentile observation windows.
            </p>
            <div className="unimplemented-state__details">
              <h4>Planned Recommendation Capabilities:</h4>
              <ul>
                <li><strong>Over-Provisioning Detection:</strong> Identifies workloads reserving &gt;3x their p95 consumption.</li>
                <li><strong>OOM Risk Mitigation:</strong> Recommends memory limit increases for containers approaching limit thresholds.</li>
                <li><strong>Safety Buffers:</strong> All recommendations disclose their observation window and configurable safety margins.</li>
                <li><strong>Read-Only Safety:</strong> Recommendations are purely advisory; KubeWatch will never modify live manifests automatically.</li>
              </ul>
            </div>
            <div className="card-note mt-4">
              <Info size={15} className="card-note__icon" />
              <span className="card-note__text">
                <strong>Data Integrity Notice:</strong> Synthetic recommendations or fictional cost savings are strictly never displayed.
              </span>
            </div>
          </div>
        </div>
      ) : isError ? (
        <div className="card p-6">
          <EmptyState
            icon={AlertTriangle}
            title="Unable to Retrieve Recommendations"
            description={error?.message || 'Error occurred communicating with the recommendation engine.'}
            action={
              <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
                Retry
              </button>
            }
          />
        </div>
      ) : recommendations && recommendations.length > 0 ? (
        <div className="grid-cards grid-cards--2">
          {recommendations.map((rec) => (
            <div key={rec.id} className="card recommendation-card">
              <div className="card__header">
                <div className="recommendation-card__title-group">
                  <Lightbulb size={16} className="text-warning" />
                  <span className="font-mono font-medium">{rec.namespace}/{rec.workload_name}</span>
                </div>
                <StatusBadge status={rec.status} />
              </div>
              <div className="card__body">
                <p className="recommendation-card__reasoning">{rec.reasoning}</p>
                <div className="recommendation-card__specs">
                  <div className="spec-comparison">
                    <span className="spec-label">Current:</span>
                    <pre className="spec-code">{JSON.stringify(rec.current_spec, null, 2)}</pre>
                  </div>
                  <div className="spec-comparison">
                    <span className="spec-label">Recommended:</span>
                    <pre className="spec-code">{JSON.stringify(rec.recommended_spec, null, 2)}</pre>
                  </div>
                </div>
                {rec.estimated_savings && (
                  <div className="recommendation-card__savings">
                    Estimated resource reduction: <strong>{rec.estimated_savings}</strong>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="card">
          <EmptyState
            icon={CheckCircle}
            title="No Pending Recommendations"
            description="All active workloads are currently sized within normal utilization guidelines."
          />
        </div>
      )}
    </div>
  );
};
