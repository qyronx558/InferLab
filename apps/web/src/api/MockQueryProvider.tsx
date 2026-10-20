import { useState, type ReactNode } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { createMockQueryClient } from './query-client';

export function MockQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(createMockQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
