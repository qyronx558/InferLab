import { queryOptions, useQuery } from '@tanstack/react-query';
import { mockApi, MockCancelledError, type MockScenario } from './mock-api';
import { mockKey } from './query-client';
import type { ContractCatalog, ExecutionState, ResourceName } from './types';
import { toDashboardView } from '@/data/demo';

export function mockQueryOptions<K extends ResourceName>(
  resource: K,
  scenario: MockScenario = 'success',
) {
  return queryOptions({
    queryKey: mockKey(resource, scenario),
    queryFn: ({ signal }) => mockApi.get(resource, scenario, signal),
    retry: false,
    staleTime: Infinity,
    networkMode: 'always',
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
}

export function useRegistryQuery(scenario: MockScenario = 'success') {
  return useQuery(mockQueryOptions('registry', scenario));
}
export function useExperimentsQuery(scenario: MockScenario = 'success') {
  return useQuery(mockQueryOptions('experiments', scenario));
}
export function useRunMetricsQuery(scenario: MockScenario = 'success') {
  return useQuery(mockQueryOptions('runs', scenario));
}
export function useSummariesQuery(scenario: MockScenario = 'success') {
  return useQuery(mockQueryOptions('summaries', scenario));
}
export function usePublishedReportsQuery(scenario: MockScenario = 'success') {
  return useQuery(mockQueryOptions('reports', scenario));
}
export function useWorkerHeartbeatQuery(scenario: MockScenario = 'success') {
  return useQuery(mockQueryOptions('worker', scenario));
}

export function resourceState(query: {
  isPending: boolean;
  isFetching: boolean;
  error: Error | null;
  data: { state: 'complete' | 'unavailable' } | undefined;
}): ExecutionState {
  if (query.isPending) return 'pending';
  if (query.error instanceof MockCancelledError) return 'cancelled';
  if (query.error) return 'failed';
  if (!query.data) return 'unavailable';
  if (query.data?.state === 'unavailable') return 'unavailable';
  if (query.isFetching) return 'running';
  return 'complete';
}

export function useDemoData() {
  const registry = useRegistryQuery();
  const experiments = useExperimentsQuery();
  const runs = useRunMetricsQuery();
  const reports = usePublishedReportsQuery();
  if (
    registry.data?.state !== 'complete' ||
    experiments.data?.state !== 'complete' ||
    runs.data?.state !== 'complete' ||
    reports.data?.state !== 'complete'
  ) {
    throw new Error('Demo pages must render inside the ready contract boundary');
  }
  return toDashboardView({
    registry: registry.data,
    experiments: experiments.data,
    runs: runs.data,
    reports: reports.data,
  });
}

export type ReadyDashboard = Pick<ContractCatalog, 'registry' | 'experiments' | 'runs' | 'reports'>;
