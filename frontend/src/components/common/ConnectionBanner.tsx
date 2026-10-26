import type React from 'react';
import { AlertCircle, AlertTriangle, RefreshCw } from 'lucide-react';
import type { HealthData } from '../../api/types';
import { API_BASE_URL } from '../../api/client';

interface ConnectionBannerProps {
  health?: HealthData | null;
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  onRetry?: () => void;
}

export const ConnectionBanner: React.FC<ConnectionBannerProps> = ({
  health,
  isLoading,
  isError,
  error,
  onRetry,
}) => {
  // If backend is completely offline or unreachable
  if (isError) {
    return (
      <div className="connection-banner connection-banner--error" role="alert">
        <div className="connection-banner__content">
          <AlertCircle className="connection-banner__icon" size={18} />
          <div className="connection-banner__text">
            <strong>Backend Unreachable:</strong> Cannot connect to KubeWatch API.
            Ensure the FastAPI server is running on <code>{API_BASE_URL}</code>.
            {error && <span className="connection-banner__detail"> ({error.message})</span>}
          </div>
        </div>
        {onRetry && (
          <button type="button" className="btn btn--secondary btn--sm" onClick={onRetry}>
            <RefreshCw size={13} className="icon-mr" />
            Reconnect
          </button>
        )}
      </div>
    );
  }

  if (isLoading || !health) {
    return null;
  }

  const k8sComponent = health.components.find((c) => c.name.toLowerCase() === 'kubernetes');
  const promComponent = health.components.find((c) => c.name.toLowerCase() === 'prometheus');

  const k8sHealthy = k8sComponent?.healthy ?? false;
  const promHealthy = promComponent?.healthy ?? false;

  // If degraded: e.g. Prometheus is down or K8s is down
  if (!k8sHealthy || !promHealthy) {
    return (
      <div className="connection-banner connection-banner--warning" role="status">
        <div className="connection-banner__content">
          <AlertTriangle className="connection-banner__icon" size={18} />
          <div className="connection-banner__text">
            <strong>Degraded Connectivity:</strong>
            {!k8sHealthy && (
              <span className="connection-banner__pill connection-banner__pill--error">
                Kubernetes API Offline
              </span>
            )}
            {!promHealthy && (
              <span className="connection-banner__pill connection-banner__pill--warning">
                Prometheus Offline (Metrics unavailable — port-forward 9090)
              </span>
            )}
          </div>
        </div>
        {onRetry && (
          <button type="button" className="btn btn--ghost btn--sm" onClick={onRetry} title="Refresh connection status">
            <RefreshCw size={13} />
          </button>
        )}
      </div>
    );
  }

  return null;
};
