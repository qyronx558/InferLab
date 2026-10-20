import { mockFixtures } from './fixtures.generated';
import type { ContractCatalog, ResourceName } from './types';

export type MockScenario = 'success' | 'pending' | 'error' | 'unavailable' | 'cancelled';

export class MockCancelledError extends Error {
  constructor() {
    super('Demo request cancelled');
    this.name = 'MockCancelledError';
  }
}

const fixtures: ContractCatalog = mockFixtures;
const unavailable: ContractCatalog = {
  ...fixtures,
  registry: fixtures.unavailable_response,
  experiments: fixtures.unavailable_response,
  runs: fixtures.unavailable_response,
  summaries: fixtures.unavailable_response,
  reports: fixtures.unavailable_response,
  worker: fixtures.unavailable_response,
};

export function createMockApi() {
  return {
    async get<K extends ResourceName>(
      resource: K,
      scenario: MockScenario = 'success',
      signal?: AbortSignal,
    ): Promise<ContractCatalog[K]> {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      if (scenario === 'pending') {
        return new Promise<never>((_resolve, reject) => {
          signal?.addEventListener(
            'abort',
            () => reject(new DOMException('Aborted', 'AbortError')),
            { once: true },
          );
        });
      }
      if (scenario === 'error')
        throw new Error('Simulated transport failure; no HTTP request made');
      if (scenario === 'cancelled') throw new MockCancelledError();
      return structuredClone((scenario === 'unavailable' ? unavailable : fixtures)[resource]);
    },
  };
}

export const mockApi = createMockApi();
