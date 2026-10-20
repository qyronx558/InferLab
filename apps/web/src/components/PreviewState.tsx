import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { EmptyState } from './EmptyState';
import { ErrorState } from './ErrorState';
import { Skeleton } from './Skeleton';

export function PreviewState({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const reset = () => setParams({});
  if (params.get('state') === 'empty')
    return (
      <EmptyState
        title="No published results yet"
        description="This is the empty preview. Restore the synthetic dataset to explore the interface."
        onReset={reset}
      />
    );
  if (params.get('state') === 'error') return <ErrorState onRetry={reset} />;
  if (params.get('state') === 'loading') return <Skeleton />;
  return children;
}
