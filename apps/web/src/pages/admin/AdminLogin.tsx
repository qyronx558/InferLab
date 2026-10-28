import { useMutation } from '@tanstack/react-query';
import { KeyRound, LockKeyhole } from 'lucide-react';
import { useState, type FormEvent } from 'react';
import { Navigate, useLocation, useNavigate } from 'react-router-dom';
import { friendlyApiMessage } from '@/api/client';
import { useAuth } from '@/admin/useAuth';
import { Button } from '@/components/ui/button';
import { PageHeading } from '@/components/PageHeading';

export function AdminLogin() {
  const { session, isLoading, login } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const [fieldError, setFieldError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: login,
    onSuccess: () => {
      const from = (location.state as { from?: unknown } | null)?.from;
      navigate(
        typeof from === 'string' && from.startsWith('/admin') ? from : '/admin/experiments',
        {
          replace: true,
        },
      );
    },
  });

  if (!isLoading && session) {
    return <Navigate to="/admin/experiments" replace />;
  }

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!password) {
      setFieldError('Enter the admin password.');
      return;
    }
    setFieldError(null);
    mutation.mutate(password);
  };

  return (
    <>
      <title>Admin sign in · InferLab</title>
      <main id="main-content" className="admin-login-page">
        <div className="admin-login-card">
          <PageHeading
            eyebrow="LOCAL ADMIN CONSOLE"
            title="Sign in"
            description="This console can queue local experiments and control jobs. It is available only on this machine over trusted HTTPS."
            titleSuffix="InferLab admin"
          />

          <div className="admin-security-note">
            <LockKeyhole size={16} aria-hidden="true" />
            <p>
              The session cookie is HttpOnly and Secure. Mutations require an exact Origin check and
              a CSRF token. Public pages never call this API.
            </p>
          </div>

          <form onSubmit={submit} noValidate aria-labelledby="page-heading">
            {mutation.error && (
              <div className="admin-form-error" role="alert">
                <p>{friendlyApiMessage(mutation.error)}</p>
              </div>
            )}
            <div className="admin-field">
              <label htmlFor="admin-password" className="admin-field-label">
                Admin password
              </label>
              <div className="admin-input-with-icon">
                <KeyRound size={16} aria-hidden="true" />
                <input
                  id="admin-password"
                  name="password"
                  type="password"
                  autoComplete="current-password"
                  className="admin-input"
                  value={password}
                  onChange={(event) => {
                    setPassword(event.target.value);
                    setFieldError(null);
                  }}
                  aria-invalid={fieldError ? true : undefined}
                  aria-describedby={fieldError ? 'admin-password-error' : 'admin-password-hint'}
                  disabled={mutation.isPending}
                />
              </div>
              <p id="admin-password-hint" className="admin-field-hint">
                Provisioned by the operator as an Argon2id hash. There is no registration or reset
                flow.
              </p>
              {fieldError && (
                <p id="admin-password-error" className="admin-field-error">
                  {fieldError}
                </p>
              )}
            </div>
            <Button type="submit" disabled={mutation.isPending} className="w-full">
              {mutation.isPending ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          <p className="mt-5 text-center text-xs text-muted-foreground">
            Administration is local only. Return to the{' '}
            <a className="inline-link" href="/">
              public read-only site
            </a>
            .
          </p>
        </div>
      </main>
    </>
  );
}
