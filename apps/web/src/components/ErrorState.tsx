import { TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function ErrorState({
  onRetry,
  title = 'Unable to load this preview',
  description = 'This is a simulated error. No backend request was made.',
  actionLabel = 'Restore demo data',
}: {
  onRetry: () => void;
  title?: string;
  description?: string;
  actionLabel?: string;
}) {
  return (
    <div className="state-panel" role="alert">
      <div className="state-icon text-red-700">
        <TriangleAlert size={24} aria-hidden="true" />
      </div>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="max-w-md text-sm text-muted-foreground">{description}</p>
      <Button variant="outline" onClick={onRetry}>
        {actionLabel}
      </Button>
    </div>
  );
}
