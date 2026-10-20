import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { Skeleton } from './Skeleton';
import {
  resourceState,
  useExperimentsQuery,
  usePublishedReportsQuery,
  useRegistryQuery,
} from '@/api/hooks';
import type { MockScenario } from '@/api/mock-api';

export function PreviewState({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const preview = params.get('state');
  const scenario: MockScenario =
    preview === 'loading'
      ? 'pending'
      : preview === 'error'
        ? 'error'
        : preview === 'unavailable'
          ? 'unavailable'
          : preview === 'cancelled'
            ? 'cancelled'
            : 'success';
  const registry = useRegistryQuery(scenario);
  const experiments = useExperimentsQuery(scenario);
  const reports = usePublishedReportsQuery(scenario);
  const state =
    [resourceState(registry), resourceState(experiments), resourceState(reports)].find(
      (value) => value !== 'complete',
    ) ?? 'complete';
  const reset = () => setParams({});
  if (preview === 'empty')
    return (
      <EmptyState
        title="No published results yet"
        description="This is the empty preview. Restore the synthetic dataset to explore the interface."
        onReset={reset}
      />
    );
  if (state === 'pending' || state === 'running') return <Skeleton />;
  if (state === 'failed') return <ErrorState onRetry={reset} />;
  if (state === 'cancelled')
    return (
      <EmptyState
        title="Preview request cancelled"
        description="Only this mock request was cancelled; no experiment or GPU job was changed."
        onReset={reset}
      />
    );
  if (state === 'unavailable')
    return (
      <EmptyState
        title="Experiment service unavailable"
        description="This is an unavailable API fixture. Published demo snapshots are cached separately; no job has been marked failed."
        onReset={reset}
      />
    );
  return children;
}
