import { TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function ErrorState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="state-panel" role="alert">
      <div className="state-icon text-red-700">
        <TriangleAlert size={24} aria-hidden="true" />
      </div>
      <h2 className="text-lg font-semibold">Unable to load this preview</h2>
      <p className="max-w-sm text-sm text-muted-foreground">
        This is a simulated error. No backend request was made.
      </p>
      <Button variant="outline" onClick={onRetry}>
        Restore demo data
      </Button>
    </div>
  );
}
