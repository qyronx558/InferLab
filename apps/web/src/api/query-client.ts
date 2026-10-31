import { QueryClient } from '@tanstack/react-query';
import { mockFixtures } from './fixtures.generated';
import type { ResourceName } from './types';
import type { MockScenario } from './mock-api';
import type { SnapshotResources } from './snapshot';

export const mockKey = (resource: ResourceName, scenario: MockScenario = 'success') =>
  ['demo-contract-v1', resource, scenario] as const;

export function createMockQueryClient(seedSnapshots = true) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Infinity,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        networkMode: 'always',
      },
      mutations: { retry: false, networkMode: 'always' },
    },
  });
  // Reviewed local snapshots remain readable when navigator/network/worker is offline.
  // No private job is submitted, retried or replayed by this provider.
  if (seedSnapshots) {
    for (const resource of [
      'registry',
      'experiments',
      'runs',
      'summaries',
      'reports',
      'worker',
    ] as const) {
      client.setQueryData(mockKey(resource), structuredClone(mockFixtures[resource]));
    }
  }
  return client;
}

export function createSnapshotQueryClient(resources: SnapshotResources) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
        staleTime: Infinity,
        refetchOnWindowFocus: false,
        refetchOnReconnect: false,
        networkMode: 'always',
      },
      mutations: { retry: false, networkMode: 'always' },
    },
  });
  for (const resource of [
    'registry',
    'experiments',
    'runs',
    'summaries',
    'reports',
    'worker',
  ] as const) {
    client.setQueryData(mockKey(resource), structuredClone(resources[resource]));
  }
  return client;
}
