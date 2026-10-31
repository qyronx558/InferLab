import { ChevronRight, Menu } from 'lucide-react';
import { useLocation, useSearchParams } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { SheetTrigger } from '@/components/ui/sheet';
import { useSnapshotInfo } from '@/api/snapshot-context';

const names: Record<string, string> = {
  '/': 'Overview',
  '/experiments': 'Experiments',
  '/compare': 'Compare',
  '/compare/report': 'Comparison report',
  '/models': 'Models',
  '/reports': 'Reports',
  '/methodology': 'Methodology',
};
export function Header() {
  const { pathname } = useLocation();
  const [params, setParams] = useSearchParams();
  const snapshot = useSnapshotInfo();
  return (
    <header className="workspace-header">
      <div className="flex min-w-0 items-center gap-3">
        <SheetTrigger asChild>
          <Button size="icon" variant="ghost" className="lg:hidden" aria-label="Open navigation">
            <Menu aria-hidden="true" />
          </Button>
        </SheetTrigger>
        <div className="flex items-center gap-2 text-xs">
          <span className="hidden text-muted-foreground sm:inline">Workspace</span>
          <ChevronRight size={12} className="hidden text-slate-400 sm:block" aria-hidden="true" />
          <span className="font-medium">{names[pathname] ?? 'Page not found'}</span>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <label className="hidden items-center gap-2 text-xs text-muted-foreground md:flex">
          Preview state
          <select
            aria-label="Preview state"
            className="native-select py-1"
            value={params.get('state') ?? 'populated'}
            onChange={(e) =>
              setParams(e.target.value === 'populated' ? {} : { state: e.target.value })
            }
          >
            <option value="populated">Populated</option>
            <option value="empty">Empty</option>
            <option value="error">Error</option>
            <option value="loading">Loading</option>
            <option value="unavailable">Unavailable</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        <Badge variant="outline" className="demo-badge">
          {snapshot.label}
        </Badge>
        <span className="header-avatar" aria-label="Read-only preview">
          IL
        </span>
      </div>
    </header>
  );
}
