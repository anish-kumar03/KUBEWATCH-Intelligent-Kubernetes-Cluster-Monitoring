import React, { useState, useMemo } from 'react';
import {
  ResponsiveContainer,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import { Cpu, Database, Clock, AlertTriangle, Layers, Info } from 'lucide-react';
import { LoadingState } from '../components/common/LoadingState';
import { ErrorState } from '../components/common/ErrorState';
import { EmptyState } from '../components/common/EmptyState';
import type { TimeRangeOption } from '../api/queries';
import type { MetricsResult } from '../api/types';

interface PerformancePageProps {
  nodeCpuMetrics?: MetricsResult | null;
  nodeMemMetrics?: MetricsResult | null;
  podCpuMetrics?: MetricsResult | null;
  podMemMetrics?: MetricsResult | null;
  timeRange: TimeRangeOption;
  onTimeRangeChange: (range: TimeRangeOption) => void;
  isLoading: boolean;
  isError: boolean;
  error?: Error | null;
  onRetry: () => void;
}

// Transform Prometheus series list into merged chart points
interface ChartDataPoint {
  time: string;
  timestamp: number;
  [seriesKey: string]: number | string;
}

function transformSeriesToChartData(metrics?: MetricsResult | null): {
  data: ChartDataPoint[];
  seriesKeys: string[];
} {
  if (!metrics || !metrics.series || metrics.series.length === 0) {
    return { data: [], seriesKeys: [] };
  }

  const seriesKeys: string[] = [];
  const timeMap = new Map<number, ChartDataPoint>();

  metrics.series.forEach((s, idx) => {
    // Determine a readable label: instance, pod, or fallback
    const label =
      s.metric_labels.instance ||
      s.metric_labels.pod ||
      s.metric_labels.node ||
      `Series ${idx + 1}`;

    const uniqueKey = seriesKeys.includes(label) ? `${label} (${idx})` : label;
    seriesKeys.push(uniqueKey);

    s.values.forEach((dp) => {
      // Round timestamp to nearest 10 seconds for clean alignment
      const roundedTs = Math.round(dp.timestamp / 10) * 10;
      let point = timeMap.get(roundedTs);
      if (!point) {
        const d = new Date(dp.timestamp * 1000);
        point = {
          time: d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          timestamp: roundedTs,
        };
        timeMap.set(roundedTs, point);
      }
      point[uniqueKey] = Math.round(dp.value * 100) / 100;
    });
  });

  const sortedPoints = Array.from(timeMap.values()).sort((a, b) => a.timestamp - b.timestamp);
  return { data: sortedPoints, seriesKeys };
}

// Chart line colors matching developer-tools palette
const CHART_PALETTE = ['#38bdf8', '#818cf8', '#34d399', '#f472b6', '#fbbf24', '#a78bfa'];

export const PerformancePage: React.FC<PerformancePageProps> = ({
  nodeCpuMetrics,
  nodeMemMetrics,
  podCpuMetrics,
  podMemMetrics,
  timeRange,
  onTimeRangeChange,
  isLoading,
  isError,
  error,
  onRetry,
}) => {
  const [metricView, setMetricView] = useState<'nodes' | 'pods'>('nodes');

  const { data: nodeCpuData, seriesKeys: nodeCpuKeys } = useMemo(
    () => transformSeriesToChartData(nodeCpuMetrics),
    [nodeCpuMetrics],
  );

  const { data: nodeMemData, seriesKeys: nodeMemKeys } = useMemo(
    () => transformSeriesToChartData(nodeMemMetrics),
    [nodeMemMetrics],
  );

  const { data: podCpuData, seriesKeys: podCpuKeys } = useMemo(
    () => transformSeriesToChartData(podCpuMetrics),
    [podCpuMetrics],
  );

  const { data: podMemData, seriesKeys: podMemKeys } = useMemo(
    () => transformSeriesToChartData(podMemMetrics),
    [podMemMetrics],
  );

  const activeCpuData = metricView === 'nodes' ? nodeCpuData : podCpuData;
  const activeCpuKeys = metricView === 'nodes' ? nodeCpuKeys : podCpuKeys;
  const activeCpuError = metricView === 'nodes' ? nodeCpuMetrics?.error : podCpuMetrics?.error;

  const activeMemData = metricView === 'nodes' ? nodeMemData : podMemData;
  const activeMemKeys = metricView === 'nodes' ? nodeMemKeys : podMemKeys;
  const activeMemError = metricView === 'nodes' ? nodeMemMetrics?.error : podMemMetrics?.error;

  const isPrometheusOffline =
    (nodeCpuMetrics?.error && nodeCpuMetrics.error.toLowerCase().includes('unreachable')) ||
    (nodeMemMetrics?.error && nodeMemMetrics.error.toLowerCase().includes('unreachable'));

  return (
    <div className="page-content" id="panel-performance" role="tabpanel" aria-labelledby="tab-performance">
      {/* Prometheus status banner if offline */}
      {isPrometheusOffline && (
        <div className="callout-banner callout-banner--warning">
          <AlertTriangle size={18} className="callout-banner__icon" />
          <div className="callout-banner__content">
            <strong>Prometheus Metrics Unavailable:</strong> Cannot query timeseries from Prometheus.
            To view live metrics locally, start port-forwarding with:
            <pre className="inline-code">kubectl port-forward -n monitoring svc/prometheus-k8s 9090:9090</pre>
          </div>
        </div>
      )}

      {/* Header controls */}
      <div className="controls-bar">
        <div className="controls-bar__left">
          <div className="segmented-control" role="group" aria-label="Metric Scope">
            <button
              type="button"
              className={`segmented-control__btn ${metricView === 'nodes' ? 'segmented-control__btn--active' : ''}`}
              onClick={() => setMetricView('nodes')}
            >
              <Cpu size={14} className="icon-mr" />
              <span>Node Metrics</span>
            </button>
            <button
              type="button"
              className={`segmented-control__btn ${metricView === 'pods' ? 'segmented-control__btn--active' : ''}`}
              onClick={() => setMetricView('pods')}
            >
              <Layers size={14} className="icon-mr" />
              <span>Pod Workloads</span>
            </button>
          </div>
        </div>

        <div className="controls-bar__right">
          <div className="filter-group">
            <span className="filter-label">
              <Clock size={13} className="icon-mr" />
              Time Range:
            </span>
            <div className="range-button-group" role="group" aria-label="Time range selector">
              {(['1h', '6h', '24h', '7d'] as TimeRangeOption[]).map((r) => (
                <button
                  key={r}
                  type="button"
                  className={`btn-range ${timeRange === r ? 'btn-range--active' : ''}`}
                  onClick={() => onTimeRangeChange(r)}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {isLoading && (!nodeCpuMetrics || !nodeMemMetrics) ? (
        <LoadingState message="Fetching time-series metrics from Prometheus..." height="350px" />
      ) : isError ? (
        <ErrorState
          title="Failed to Load Performance Metrics"
          message={error?.message || 'Error occurred querying the backend metrics endpoint.'}
          onRetry={onRetry}
        />
      ) : (
        <div className="charts-grid">
          {/* CPU Chart */}
          <div className="card chart-card">
            <div className="card__header">
              <div className="chart-card__title-group">
                <Cpu size={16} className="text-primary" />
                <h3 className="card__title">
                  {metricView === 'nodes' ? 'Node CPU Utilization (%)' : 'Pod CPU Usage (Cores)'}
                </h3>
              </div>
              <span className="text-xs text-muted font-mono">
                {metricView === 'nodes' ? 'node_cpu_usage_percent' : 'pod_cpu_usage_cores'}
              </span>
            </div>

            <div className="card__body">
              {activeCpuError ? (
                <div className="chart-unavailable">
                  <AlertTriangle size={20} className="text-warning mb-2" />
                  <span className="font-medium">Metrics Offline</span>
                  <span className="text-sm text-muted text-center mt-1">{activeCpuError}</span>
                </div>
              ) : activeCpuData.length > 0 ? (
                <div className="chart-container" style={{ width: '100%', height: 280 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={activeCpuData} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                      <defs>
                        {activeCpuKeys.map((key, i) => {
                          const color = CHART_PALETTE[i % CHART_PALETTE.length];
                          return (
                            <linearGradient key={key} id={`grad-cpu-${i}`} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor={color} stopOpacity={0.35} />
                              <stop offset="95%" stopColor={color} stopOpacity={0.0} />
                            </linearGradient>
                          );
                        })}
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2e303a" vertical={false} />
                      <XAxis dataKey="time" stroke="#71717a" fontSize={11} tickLine={false} />
                      <YAxis stroke="#71717a" fontSize={11} tickLine={false} unit={metricView === 'nodes' ? '%' : ''} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#18181b',
                          borderColor: '#3f3f46',
                          borderRadius: '6px',
                          color: '#f4f4f5',
                          fontSize: '12px',
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                      {activeCpuKeys.map((key, i) => {
                        const color = CHART_PALETTE[i % CHART_PALETTE.length];
                        return (
                          <Area
                            key={key}
                            type="monotone"
                            dataKey={key}
                            stroke={color}
                            strokeWidth={2}
                            fillOpacity={1}
                            fill={`url(#grad-cpu-${i})`}
                          />
                        );
                      })}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  icon={Cpu}
                  title="No CPU Metrics Available"
                  description="Prometheus returned zero data points for this time window. Verify kube-state-metrics and node-exporter are running."
                  height="260px"
                />
              )}
            </div>
          </div>

          {/* Memory Chart */}
          <div className="card chart-card">
            <div className="card__header">
              <div className="chart-card__title-group">
                <Database size={16} className="text-primary" />
                <h3 className="card__title">
                  {metricView === 'nodes' ? 'Node Memory Utilization (%)' : 'Pod Memory Usage (Bytes)'}
                </h3>
              </div>
              <span className="text-xs text-muted font-mono">
                {metricView === 'nodes' ? 'node_memory_usage_percent' : 'pod_memory_usage_bytes'}
              </span>
            </div>

            <div className="card__body">
              {activeMemError ? (
                <div className="chart-unavailable">
                  <AlertTriangle size={20} className="text-warning mb-2" />
                  <span className="font-medium">Metrics Offline</span>
                  <span className="text-sm text-muted text-center mt-1">{activeMemError}</span>
                </div>
              ) : activeMemData.length > 0 ? (
                <div className="chart-container" style={{ width: '100%', height: 280 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={activeMemData} margin={{ top: 10, right: 20, left: -10, bottom: 0 }}>
                      <defs>
                        {activeMemKeys.map((key, i) => {
                          const color = CHART_PALETTE[(i + 2) % CHART_PALETTE.length];
                          return (
                            <linearGradient key={key} id={`grad-mem-${i}`} x1="0" y1="0" x2="0" y2="1">
                              <stop offset="5%" stopColor={color} stopOpacity={0.35} />
                              <stop offset="95%" stopColor={color} stopOpacity={0.0} />
                            </linearGradient>
                          );
                        })}
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="#2e303a" vertical={false} />
                      <XAxis dataKey="time" stroke="#71717a" fontSize={11} tickLine={false} />
                      <YAxis stroke="#71717a" fontSize={11} tickLine={false} unit={metricView === 'nodes' ? '%' : ''} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#18181b',
                          borderColor: '#3f3f46',
                          borderRadius: '6px',
                          color: '#f4f4f5',
                          fontSize: '12px',
                        }}
                      />
                      <Legend wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                      {activeMemKeys.map((key, i) => {
                        const color = CHART_PALETTE[(i + 2) % CHART_PALETTE.length];
                        return (
                          <Area
                            key={key}
                            type="monotone"
                            dataKey={key}
                            stroke={color}
                            strokeWidth={2}
                            fillOpacity={1}
                            fill={`url(#grad-mem-${i})`}
                          />
                        );
                      })}
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
              ) : (
                <EmptyState
                  icon={Database}
                  title="No Memory Metrics Available"
                  description="Prometheus returned zero data points for this time window. Verify kube-state-metrics and node-exporter are running."
                  height="260px"
                />
              )}
            </div>
          </div>
        </div>
      )}

      {/* Observability footer note */}
      <div className="card-note mt-4">
        <Info size={15} className="card-note__icon" />
        <span className="card-note__text">
          <strong>Data Integrity Principle:</strong> KubeWatch renders genuine Prometheus measurements directly from your cluster.
          Missing metrics are explicitly marked as unavailable rather than coerced to 0% to prevent misleading performance diagnostics.
        </span>
      </div>
    </div>
  );
};
