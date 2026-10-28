import { LogOut, Plus, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';
import { friendlyApiMessage } from '@/api/client';
import { useAuth } from '@/admin/useAuth';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export function AdminShell() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [signingOut, setSigningOut] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const signOut = async () => {
    setSigningOut(true);
    setError(null);
    try {
      await logout();
      navigate('/admin/login', { replace: true });
    } catch (cause) {
      setError(friendlyApiMessage(cause));
    } finally {
      setSigningOut(false);
    }
  };

  return (
    <>
      <a className="skip-link" href="#main-content">
        Skip to admin content
      </a>
      <header className="admin-header">
        <div className="admin-header-brand">
          <Link to="/" className="admin-brand-link">
            <ShieldCheck size={20} aria-hidden="true" />
            <span>InferLab</span>
          </Link>
          <Badge variant="outline" className="admin-badge">
            LOCAL ADMIN
          </Badge>
        </div>
        <nav aria-label="Admin navigation" className="admin-nav">
          <NavLink
            to="/admin/experiments"
            end
            className={({ isActive }) => cn('admin-nav-link', isActive && 'active')}
          >
            Experiments
          </NavLink>
          <NavLink
            to="/admin/experiments/new"
            className={({ isActive }) => cn('admin-nav-link', isActive && 'active')}
          >
            <Plus size={14} aria-hidden="true" />
            New experiment
          </NavLink>
        </nav>
        <div className="admin-header-actions">
          <Link to="/" className="admin-public-link">
            Public site
          </Link>
          <Button variant="outline" size="sm" onClick={() => void signOut()} disabled={signingOut}>
            <LogOut size={14} aria-hidden="true" />
            {signingOut ? 'Signing out…' : 'Sign out'}
          </Button>
        </div>
      </header>
      {error && (
        <div className="admin-global-alert" role="alert">
          Sign-out failed: {error}
        </div>
      )}
      <main id="main-content" className="admin-main">
        <Outlet />
      </main>
    </>
  );
}
