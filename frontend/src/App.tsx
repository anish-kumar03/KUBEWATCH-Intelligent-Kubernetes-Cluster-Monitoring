import { useState } from 'react';
import { QueryClient, QueryClientProvider, useQueryClient, useIsFetching } from '@tanstack/react-query';
import { Header } from './components/layout/Header';
import { Navigation, type TabId } from './components/layout/Navigation';
import { ConnectionBanner } from './components/common/ConnectionBanner';
import { OverviewPage } from './pages/OverviewPage';
import { WorkloadsPage } from './pages/WorkloadsPage';
import { PerformancePage } from './pages/PerformancePage';
import { IncidentsPage } from './pages/IncidentsPage';
import { RecommendationsPage } from './pages/RecommendationsPage';
import {
  useHealth,
  useClusterOverview,
  useNodes,
  usePods,
  useDeployments,
  useNodeCpuMetrics,
  useNodeMemoryMetrics,
  usePodCpuMetrics,
  usePodMemoryMetrics,
  useIncidents,
  useRecommendations,
  type TimeRangeOption,
} from './api/queries';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: true,
      retry: (failureCount, error) => {
        // Don't retry 404/501 unimplemented endpoints
        if (error && 'isNotImplemented' in error && (error as { isNotImplemented: boolean }).isNotImplemented) {
          return false;
        }
        return failureCount < 2;
      },
      staleTime: 5000,
    },
  },
});

function Dashboard() {
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [refetchInterval, setRefetchInterval] = useState<number>(15000);
  const [selectedNamespace, setSelectedNamespace] = useState<string>('');
  const [timeRange, setTimeRange] = useState<TimeRangeOption>('1h');
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());

  const client = useQueryClient();
  const isFetchingCount = useIsFetching();

  // Queries
  const healthQuery = useHealth(refetchInterval);
  const overviewQuery = useClusterOverview(refetchInterval);
  const nodesQuery = useNodes(refetchInterval);
  const podsQuery = usePods(selectedNamespace || undefined, refetchInterval);
  const deploymentsQuery = useDeployments(selectedNamespace || undefined, refetchInterval);

  const nodeCpuQuery = useNodeCpuMetrics(timeRange, refetchInterval);
  const nodeMemQuery = useNodeMemoryMetrics(timeRange, refetchInterval);
  const podCpuQuery = usePodCpuMetrics(selectedNamespace || undefined, undefined, timeRange, refetchInterval);
  const podMemQuery = usePodMemoryMetrics(selectedNamespace || undefined, undefined, timeRange, refetchInterval);

  const incidentsQuery = useIncidents();
  const recommendationsQuery = useRecommendations();

  const handleRefreshAll = async () => {
    await client.invalidateQueries();
    setLastUpdated(new Date());
  };

  return (
    <div className="app-layout">
      {/* Global connection alert banner if backend is down or degraded */}
      <ConnectionBanner
        health={healthQuery.data}
        isLoading={healthQuery.isLoading}
        isError={healthQuery.isError}
        error={healthQuery.error}
        onRetry={handleRefreshAll}
      />

      {/* Top Application Header */}
      <Header
        health={healthQuery.data}
        isHealthLoading={healthQuery.isLoading}
        isHealthError={healthQuery.isError}
        isFetching={isFetchingCount > 0}
        refetchInterval={refetchInterval}
        onIntervalChange={setRefetchInterval}
        onRefreshAll={handleRefreshAll}
        lastUpdated={lastUpdated}
      />

      {/* View Navigation Tabs */}
      <Navigation
        activeTab={activeTab}
        onTabChange={setActiveTab}
        incidentsCount={incidentsQuery.data?.length ?? null}
      />

      {/* Main Page Area */}
      <main className="app-main">
        {activeTab === 'overview' && (
          <OverviewPage
            overview={overviewQuery.data}
            nodes={nodesQuery.data}
            pods={podsQuery.data}
            deployments={deploymentsQuery.data}
            health={healthQuery.data}
            isLoading={overviewQuery.isLoading || nodesQuery.isLoading}
            isError={overviewQuery.isError}
            error={overviewQuery.error}
            onNavigateTab={setActiveTab}
            onRetry={handleRefreshAll}
          />
        )}

        {activeTab === 'workloads' && (
          <WorkloadsPage
            pods={podsQuery.data}
            deployments={deploymentsQuery.data}
            isLoading={podsQuery.isLoading || deploymentsQuery.isLoading}
            isError={podsQuery.isError}
            error={podsQuery.error}
            selectedNamespace={selectedNamespace}
            onNamespaceChange={setSelectedNamespace}
            onRetry={handleRefreshAll}
          />
        )}

        {activeTab === 'performance' && (
          <PerformancePage
            nodeCpuMetrics={nodeCpuQuery.data}
            nodeMemMetrics={nodeMemQuery.data}
            podCpuMetrics={podCpuQuery.data}
            podMemMetrics={podMemQuery.data}
            timeRange={timeRange}
            onTimeRangeChange={setTimeRange}
            isLoading={nodeCpuQuery.isLoading || nodeMemQuery.isLoading}
            isError={nodeCpuQuery.isError || nodeMemQuery.isError}
            error={nodeCpuQuery.error || nodeMemQuery.error}
            onRetry={handleRefreshAll}
          />
        )}

        {activeTab === 'incidents' && (
          <IncidentsPage
            incidents={incidentsQuery.data}
            isLoading={incidentsQuery.isLoading}
            isError={incidentsQuery.isError}
            error={incidentsQuery.error}
            onRetry={() => incidentsQuery.refetch()}
          />
        )}

        {activeTab === 'recommendations' && (
          <RecommendationsPage
            recommendations={recommendationsQuery.data}
            isLoading={recommendationsQuery.isLoading}
            isError={recommendationsQuery.isError}
            error={recommendationsQuery.error}
            onRetry={() => recommendationsQuery.refetch()}
          />
        )}
      </main>

      {/* Footer */}
      <footer className="app-footer">
        <div className="app-footer__content">
          <span>KubeWatch v0.1.0 • Intelligent Kubernetes Cluster Monitoring</span>
          <span className="app-footer__badge">Read-Only Safe Mode</span>
        </div>
      </footer>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <Dashboard />
    </QueryClientProvider>
  );
}
