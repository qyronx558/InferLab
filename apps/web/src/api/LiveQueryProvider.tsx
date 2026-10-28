import { QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { createLiveQueryClient } from './liveQueryClient';

export function LiveQueryProvider({ children }: { children: ReactNode }) {
  const [client] = useState(createLiveQueryClient);
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
