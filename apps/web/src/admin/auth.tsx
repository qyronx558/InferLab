import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useMemo, type ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { ApiError, apiClient, friendlyApiMessage } from '@/api/client';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/Skeleton';
import { AuthContext, sessionKey, type AuthValue } from './authContext';
import { useAuth } from './useAuth';

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const session = useQuery({
    queryKey: sessionKey,
    queryFn: ({ signal }) => apiClient.getSession(signal),
    retry: false,
    staleTime: 60_000,
    refetchOnWindowFocus: false,
  });

  const login = useCallback(
    async (password: string) => {
      const info = await apiClient.login(password);
      queryClient.setQueryData(sessionKey, info);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['live', 'experiments'], exact: true }),
        queryClient.invalidateQueries({ queryKey: ['live', 'registry'] }),
        queryClient.invalidateQueries({ queryKey: ['live', 'worker'] }),
      ]);
      return info;
    },
    [queryClient],
  );

  const logout = useCallback(async () => {
    if (!session.data) return;
    await apiClient.logout(session.data.csrf_token);
    queryClient.setQueryData(sessionKey, null);
    queryClient.removeQueries({ queryKey: ['live'], exact: false });
    queryClient.setQueryData(sessionKey, null);
  }, [queryClient, session.data]);

  const value = useMemo<AuthValue>(
    () => ({
      session: session.data ?? null,
      isLoading: session.isPending,
      error: session.error,
      retry: () => void session.refetch(),
      login,
      logout,
    }),
    [session, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { session, isLoading, error, retry } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <Skeleton label="Checking admin session" />;
  }

  if (error instanceof ApiError && error.status === 401) {
    return (
      <Navigate
        to="/admin/login"
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }

  if (error) {
    return (
      <div className="admin-centered-panel" role="alert">
        <h1 className="text-xl font-semibold">Admin session unavailable</h1>
        <p className="max-w-md text-sm text-muted-foreground">{friendlyApiMessage(error)}</p>
        <Button variant="outline" onClick={retry}>
          Retry session check
        </Button>
      </div>
    );
  }

  if (!session) {
    return (
      <Navigate
        to="/admin/login"
        replace
        state={{ from: `${location.pathname}${location.search}` }}
      />
    );
  }

  return <>{children}</>;
}
