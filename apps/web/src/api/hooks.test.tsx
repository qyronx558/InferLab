import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClientProvider, onlineManager, type QueryClient } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mockFixtures } from './fixtures.generated';
import { createMockApi } from './mock-api';
import { createMockQueryClient, mockKey } from './query-client';
import { resourceState, usePublishedReportsQuery, useWorkerHeartbeatQuery } from './hooks';

const clients: QueryClient[] = [];
function wrapper(seed = false) {
  const client = createMockQueryClient(seed);
  clients.push(client);
  return {
    client,
    wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}
afterEach(() => {
  clients.forEach((client) => client.clear());
  clients.length = 0;
  onlineManager.setOnline(true);
});

describe('typed local query boundary', () => {
  it('loads public fixtures offline without fetch or a working heartbeat', async () => {
    const fetchSpy = vi.spyOn(globalThis, 'fetch');
    onlineManager.setOnline(false);
    const setup = wrapper();
    const { result } = renderHook(
      () => ({ reports: usePublishedReportsQuery(), worker: useWorkerHeartbeatQuery() }),
      { wrapper: setup.wrapper },
    );
    await waitFor(() => expect(result.current.reports.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.worker.isSuccess).toBe(true));
    expect(result.current.reports.data?.state).toBe('complete');
    const heartbeat = result.current.worker.data;
    expect(heartbeat?.state === 'complete' && heartbeat.data.availability).toBe('offline');
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('keeps null metrics unavailable in published responses', async () => {
    const response = await createMockApi().get('reports');
    expect(response.state).toBe('complete');
    if (response.state !== 'complete') throw new Error('Expected demo reports');
    expect(response.data[0]?.summary.quality).toEqual({
      value: null,
      unit: 'score',
      unavailable_reason: 'unsupported',
    });
    expect(response.data[0]?.label).toBe('DEMO DATA');
  });

  it.each([
    ['unavailable', 'unavailable'],
    ['error', 'failed'],
    ['cancelled', 'cancelled'],
  ] as const)('represents %s independently of job completion', async (scenario, expected) => {
    const setup = wrapper();
    const { result } = renderHook(() => usePublishedReportsQuery(scenario), {
      wrapper: setup.wrapper,
    });
    await waitFor(() => expect(resourceState(result.current)).toBe(expected));
    if (expected !== 'unavailable') expect(result.current.data).toBeUndefined();
    expect(result.current.failureCount).toBeLessThanOrEqual(1);
  });

  it('distinguishes a pending load from refresh of a cached snapshot', async () => {
    const setup = wrapper();
    const { result, unmount } = renderHook(() => usePublishedReportsQuery('pending'), {
      wrapper: setup.wrapper,
    });
    expect(resourceState(result.current)).toBe('pending');
    act(() =>
      setup.client.setQueryData(
        mockKey('reports', 'pending'),
        structuredClone(mockFixtures.reports),
      ),
    );
    await waitFor(() => expect(resourceState(result.current)).toBe('running'));
    expect(result.current.data?.state).toBe('complete');
    unmount(); // aborts the mock wait; no background request survives.
  });

  it('serves independent fixture copies instead of mutating shared measurements', async () => {
    const api = createMockApi();
    const first = await api.get('registry');
    if (first.state !== 'complete') throw new Error('Expected registry');
    first.data.models.splice(0);
    const second = await api.get('registry');
    expect(second.state === 'complete' && second.data.models.length).toBe(3);
  });
});
