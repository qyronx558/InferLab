import { useEffect, useRef, useState } from 'react';
import { Link, Outlet, useLocation, useSearchParams } from 'react-router-dom';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { useSnapshotInfo } from '@/api/snapshot-context';
import { Sidebar } from './Sidebar';
import { Header } from './Header';
import { SnapshotNotice } from './SnapshotNotice';

export function AppShell() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const previousPath = useRef(pathname);
  const [params, setParams] = useSearchParams();
  const snapshot = useSnapshotInfo();
  useEffect(() => {
    const heading = document.getElementById('page-heading');
    document.title = `${heading?.textContent ?? 'Dashboard'} · InferLab demo`;
    if (previousPath.current !== pathname) heading?.focus();
    previousPath.current = pathname;
  }, [pathname]);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <a className="skip-link" href="#main-content">
        Skip to content
      </a>
      <aside className="desktop-sidebar">
        <Sidebar />
      </aside>
      <SheetContent side="left" className="mobile-sidebar">
        <SheetTitle className="sr-only">InferLab navigation</SheetTitle>
        <SheetDescription className="sr-only">
          Choose a dashboard page.{' '}
          {snapshot.status === 'snapshot'
            ? 'Content is a published static snapshot.'
            : 'All content is demo data.'}
        </SheetDescription>
        <Sidebar onNavigate={() => setOpen(false)} />
      </SheetContent>
      <div className="workspace">
        <Header />
        <main id="main-content" tabIndex={-1} className="workspace-main">
          <SnapshotNotice />
          <label className="mb-5 flex items-center justify-between text-xs text-muted-foreground md:hidden">
            Preview state
            <select
              aria-label="Mobile preview state"
              className="native-select"
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
          <Outlet />
          <footer className="workspace-footer">
            <span>
              InferLab <span aria-hidden="true">/</span> Reproducible by design.
            </span>
            <Link to="/methodology">
              Measurement methodology <span aria-hidden="true">↗</span>
            </Link>
          </footer>
        </main>
      </div>
    </Sheet>
  );
}
