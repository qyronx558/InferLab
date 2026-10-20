import { useEffect, useRef, useState } from 'react';
import { Link, Outlet, useLocation, useSearchParams } from 'react-router-dom';
import { Info } from 'lucide-react';
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet';
import { Sidebar } from './Sidebar';
import { Header } from './Header';

export function AppShell() {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  const previousPath = useRef(pathname);
  const [params, setParams] = useSearchParams();
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
          Choose a dashboard page. All content is demo data.
        </SheetDescription>
        <Sidebar onNavigate={() => setOpen(false)} />
      </SheetContent>
      <div className="workspace">
        <Header />
        <main id="main-content" tabIndex={-1} className="workspace-main">
          <div className="demo-notice">
            <Info size={15} className="shrink-0" aria-hidden="true" />
            <p>
              <strong>Demo workspace.</strong> All results and statuses are synthetic UI fixtures.
              No backend or GPU is connected.
            </p>
          </div>
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
