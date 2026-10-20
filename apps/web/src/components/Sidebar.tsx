import {
  Activity,
  ArrowUpRight,
  BookOpen,
  Boxes,
  FileChartColumn,
  FlaskConical,
  GitCompareArrows,
  Layers3,
  LayoutDashboard,
  ShieldCheck,
} from 'lucide-react';
import { NavLink, Link } from 'react-router-dom';
import { cn } from '@/lib/utils';

const workspace = [
  { label: 'Overview', to: '/', icon: LayoutDashboard },
  { label: 'Experiments', to: '/experiments', icon: FlaskConical },
  { label: 'Compare', to: '/compare', icon: GitCompareArrows },
  { label: 'Models', to: '/models', icon: Boxes },
  { label: 'Reports', to: '/reports', icon: FileChartColumn },
];
export function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="sidebar-inner">
      <Link to="/" onClick={onNavigate} className="brand" aria-label="InferLab overview">
        <span className="brand-mark">
          <Layers3 size={22} aria-hidden="true" />
        </span>
        <span>
          {import.meta.env.VITE_APP_TITLE || 'InferLab'}
          <span className="brand-caption">INFERENCE WORKSPACE</span>
        </span>
      </Link>
      <div className="workspace-label">
        <span className="small-avatar">IL</span>
        <span>
          <strong>Personal workspace</strong>
          <span>Local benchmarking lab</span>
        </span>
      </div>
      <nav aria-label="Main navigation" className="space-y-6">
        <div>
          <p className="nav-group">WORKSPACE</p>
          <div className="space-y-1">
            {workspace.map(({ label, to, icon: Icon }) => (
              <NavLink
                key={to}
                to={to}
                end={to === '/'}
                onClick={onNavigate}
                className={({ isActive }) => cn('nav-link', isActive && 'active')}
              >
                <Icon size={17} aria-hidden="true" />
                {label}
                {label === 'Experiments' && <span className="nav-count">6</span>}
              </NavLink>
            ))}
          </div>
        </div>
        <div>
          <p className="nav-group">RESOURCES</p>
          <NavLink
            to="/methodology"
            onClick={onNavigate}
            className={({ isActive }) => cn('nav-link', isActive && 'active')}
          >
            <BookOpen size={17} aria-hidden="true" />
            Methodology
          </NavLink>
        </div>
      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-note">
          <ShieldCheck size={18} aria-hidden="true" />
          <p>
            Local compute.
            <br />
            <span>Transparent results.</span>
          </p>
          <Link to="/methodology" onClick={onNavigate} aria-label="Read benchmarking principles">
            <ArrowUpRight size={16} />
          </Link>
        </div>
        <div className="flex items-center justify-between px-2 text-xs text-slate-400">
          <span className="flex items-center gap-2">
            <Activity size={13} aria-hidden="true" />
            UI preview
          </span>
          <span className="font-mono">v0.1</span>
        </div>
      </div>
    </div>
  );
}
