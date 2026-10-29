import { useEffect, useState, type ReactNode } from 'react';
import { QueryClientProvider, type QueryClient } from '@tanstack/react-query';
import { Skeleton } from '@/components/Skeleton';
import { createMockQueryClient, createSnapshotQueryClient } from './query-client';
import { loadPublishedSnapshot, toSnapshotResources } from './snapshot';
import {
  demoSnapshotInfo,
  errorSnapshotInfo,
  SnapshotContext,
  type SnapshotInfo,
} from './snapshot-context';

type ProviderState = {
  client: QueryClient;
  info: SnapshotInfo;
};

function demoState(): ProviderState {
  return { client: createMockQueryClient(), info: demoSnapshotInfo() };
}

export function MockQueryProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ProviderState | null>(() =>
    import.meta.env.MODE === 'test' ? demoState() : null,
  );

  useEffect(() => {
    if (state) return;
    let active = true;
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 4_000);
    loadPublishedSnapshot(fetch, controller.signal)
      .then((bundle) => {
        if (!active) return;
        if (!bundle) {
          setState(demoState());
          return;
        }
        setState({
          client: createSnapshotQueryClient(toSnapshotResources(bundle)),
          info: {
            status: 'snapshot',
            label: bundle.manifest.label,
            releaseId: bundle.manifest.release_id,
            publishedAt: bundle.manifest.published_at,
            error: null,
            methodology: bundle.methodology,
          },
        });
      })
      .catch((error: unknown) => {
        if (!active) return;
        setState({ client: createMockQueryClient(), info: errorSnapshotInfo(error) });
      })
      .finally(() => window.clearTimeout(timer));
    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [state]);

  if (!state) {
    return (
      <div className="admin-main">
        <Skeleton label="Loading published snapshot" />
      </div>
    );
  }

  return (
    <SnapshotContext.Provider value={state.info}>
      <QueryClientProvider client={state.client}>{children}</QueryClientProvider>
    </SnapshotContext.Provider>
  );
}
