import type React from 'react';
import { Activity, RefreshCw, Server, Zap } from 'lucide-react';
import type { HealthData } from '../../api/types';

interface HeaderProps {
  health?: HealthData | null;
  isHealthLoading: boolean;
  isHealthError: boolean;
  isFetching: boolean;
  refetchInterval: number;
  onIntervalChange: (interval: number) => void;
  onRefreshAll: () => void;
  lastUpdated?: Date;
}

export const Header: React.FC<HeaderProps> = ({
  health,
  isHealthLoading,
  isHealthError,
  isFetching,
  refetchInterval,
  onIntervalChange,
  onRefreshAll,
  lastUpdated,
}) => {
  const k8sComponent = health?.components.find((c) => c.name.toLowerCase() === 'kubernetes');
  const promComponent = health?.components.find((c) => c.name.toLowerCase() === 'prometheus');

  const backendOnline = !isHealthError && !isHealthLoading && !!health;
  const k8sOnline = backendOnline && (k8sComponent?.healthy ?? false);
  const promOnline = backendOnline && (promComponent?.healthy ?? false);

  return (
    <header className="app-header">
      <div className="app-header__brand">
        <div className="app-header__logo-wrapper">
          <Activity className="app-header__logo-icon" size={22} />
        </div>
        <div>
          <div className="app-header__title-row">
            <h1 className="app-header__title">KubeWatch</h1>
            <span className="app-header__tag">v0.1.0</span>
          </div>
          <p className="app-header__subtitle">Kubernetes Observability & Performance</p>
        </div>
      </div>

      <div className="app-header__center">
        {/* Connection status indicators */}
        <div className="conn-status-group">
          <div
            className={`conn-status-pill ${
              backendOnline ? 'conn-status-pill--ok' : 'conn-status-pill--error'
            }`}
            title="FastAPI backend connectivity"
          >
            <Server size={13} />
            <span>API: {backendOnline ? 'Online' : 'Offline'}</span>
          </div>

          <div
            className={`conn-status-pill ${
              k8sOnline ? 'conn-status-pill--ok' : 'conn-status-pill--error'
            }`}
            title="Kubernetes cluster connectivity"
          >
            <Zap size={13} />
            <span>K8s: {k8sOnline ? 'Connected' : 'Offline'}</span>
          </div>

          <div
            className={`conn-status-pill ${
              promOnline ? 'conn-status-pill--ok' : 'conn-status-pill--warning'
            }`}
            title="Prometheus metrics server connectivity"
          >
            <Activity size={13} />
            <span>Prometheus: {promOnline ? 'Live' : 'Offline'}</span>
          </div>
        </div>
      </div>

      <div className="app-header__actions">
        {lastUpdated && (
          <span className="app-header__timestamp">
            Updated {lastUpdated.toLocaleTimeString()}
          </span>
        )}

        <div className="select-wrapper">
          <label htmlFor="refresh-interval-select" className="sr-only">
            Auto Refresh Interval
          </label>
          <select
            id="refresh-interval-select"
            className="select select--sm"
            value={refetchInterval}
            onChange={(e) => onIntervalChange(Number(e.target.value))}
          >
            <option value={10000}>Auto: 10s</option>
            <option value={30000}>Auto: 30s</option>
            <option value={60000}>Auto: 1m</option>
            <option value={0}>Auto: Off</option>
          </select>
        </div>

        <button
          type="button"
          className="btn btn--secondary btn--sm"
          onClick={onRefreshAll}
          disabled={isFetching}
          title="Refresh live metrics and cluster state"
        >
          <RefreshCw size={14} className={isFetching ? 'icon-spin' : ''} />
          <span>Refresh</span>
        </button>
      </div>
    </header>
  );
};
