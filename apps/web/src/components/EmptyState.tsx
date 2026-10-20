import { SearchX } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function EmptyState({
  title = 'Nothing here yet',
  description = 'No demo experiments match these filters.',
  onReset,
}: {
  title?: string;
  description?: string;
  onReset?: () => void;
}) {
  return (
    <div className="state-panel" role="status">
      <div className="state-icon">
        <SearchX size={24} aria-hidden="true" />
      </div>
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="max-w-sm text-sm text-muted-foreground">{description}</p>
      {onReset && (
        <Button variant="outline" onClick={onReset}>
          Reset preview
        </Button>
      )}
    </div>
  );
}
