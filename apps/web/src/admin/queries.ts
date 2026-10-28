import {
  infiniteQueryOptions,
  queryOptions,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query';
import { apiClient, type CreateExperimentRequest } from '@/api/client';
import type { LiveExperiment } from '@/api/schemas';
import { useAuth } from './useAuth';

export const liveKeys = {
  registry: ['live', 'registry'] as const,
  worker: ['live', 'worker'] as const,
  experiments: ['live', 'experiments'] as const,
  experiment: (id: string) => ['live', 'experiments', id] as const,
};

export function newIdempotencyKey() {
  return `idem-${crypto.randomUUID()}`;
}

export function registryQueryOptions() {
  return queryOptions({
    queryKey: liveKeys.registry,
    queryFn: ({ signal }) => apiClient.getRegistry(signal),
    staleTime: 60_000,
  });
}

export function workerQueryOptions() {
  return queryOptions({
    queryKey: liveKeys.worker,
    queryFn: ({ signal }) => apiClient.getWorker(signal),
    refetchInterval: 10_000,
  });
}

export function experimentsQueryOptions() {
  return infiniteQueryOptions({
    queryKey: liveKeys.experiments,
    queryFn: ({ pageParam, signal }) =>
      apiClient.listExperiments({ cursor: pageParam, limit: 50 }, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (lastPage) => lastPage.next_cursor,
    refetchInterval: 10_000,
  });
}

export function experimentQueryOptions(id: string) {
  return queryOptions({
    queryKey: liveKeys.experiment(id),
    queryFn: ({ signal }) => apiClient.getExperiment(id, signal),
    refetchInterval: (query) => {
      const state = query.state.data?.job.state;
      return state === 'pending' || state === 'running' ? 5_000 : false;
    },
  });
}

export function useRegistryQuery() {
  return useQuery(registryQueryOptions());
}

export function useWorkerQuery() {
  return useQuery(workerQueryOptions());
}

export function useExperimentsQuery() {
  return useInfiniteQuery(experimentsQueryOptions());
}

export function useExperimentQuery(id: string) {
  return useQuery(experimentQueryOptions(id));
}

function useMutationSession() {
  const { session } = useAuth();
  if (!session) throw new Error('Admin mutations require an authenticated session.');
  return session;
}

function updateExperimentCaches(
  queryClient: ReturnType<typeof useQueryClient>,
  experiment: LiveExperiment,
) {
  queryClient.setQueryData(liveKeys.experiment(experiment.id), experiment);
  void queryClient.invalidateQueries({ queryKey: liveKeys.experiments, exact: true });
  void queryClient.invalidateQueries({ queryKey: liveKeys.worker });
}

export function useCreateExperiment() {
  const session = useMutationSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateExperimentRequest) =>
      apiClient.createExperiment(body, session.csrf_token),
    onSuccess: (experiment) => updateExperimentCaches(queryClient, experiment),
  });
}

export function useRenameExperiment() {
  const session = useMutationSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      name,
      version,
      key,
    }: {
      id: string;
      name: string;
      version: number;
      key: string;
    }) => apiClient.renameExperiment(id, name, version, session.csrf_token, key),
    onSuccess: (experiment) => updateExperimentCaches(queryClient, experiment),
  });
}

export function useArchiveExperiment() {
  const session = useMutationSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, version, key }: { id: string; version: number; key: string }) =>
      apiClient.archiveExperiment(id, version, session.csrf_token, key),
    onSuccess: (experiment) => {
      queryClient.removeQueries({ queryKey: liveKeys.experiment(experiment.id) });
      void queryClient.invalidateQueries({ queryKey: liveKeys.experiments, exact: true });
      void queryClient.invalidateQueries({ queryKey: liveKeys.worker });
    },
  });
}

export function useCancelExperiment() {
  const session = useMutationSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, key }: { id: string; key: string }) =>
      apiClient.cancelExperiment(id, session.csrf_token, key),
    onSuccess: (experiment) => updateExperimentCaches(queryClient, experiment),
  });
}

export function useRetryExperiment() {
  const session = useMutationSession();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, key }: { id: string; key: string }) =>
      apiClient.retryExperiment(id, session.csrf_token, key),
    onSuccess: (experiment) => updateExperimentCaches(queryClient, experiment),
  });
}
