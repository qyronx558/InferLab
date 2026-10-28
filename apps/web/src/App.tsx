import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/AppShell';
import { PreviewState } from '@/components/PreviewState';
import { Overview } from '@/pages/Overview';
import { Experiments } from '@/pages/Experiments';
import { Compare } from '@/pages/Compare';
import { Models } from '@/pages/Models';
import { Reports } from '@/pages/Reports';
import { Methodology } from '@/pages/Methodology';
import { NotFound } from '@/pages/NotFound';
import { MockQueryProvider } from '@/api/MockQueryProvider';
import { Skeleton } from '@/components/Skeleton';

const AdminSection = lazy(() => import('@/admin/AdminSection'));

export function AppRoutes() {
  return (
    <Routes>
      <Route
        element={
          <MockQueryProvider>
            <AppShell />
          </MockQueryProvider>
        }
      >
        <Route
          index
          element={
            <PreviewState>
              <Overview />
            </PreviewState>
          }
        />
        <Route
          path="experiments"
          element={
            <PreviewState>
              <Experiments />
            </PreviewState>
          }
        />
        <Route
          path="compare"
          element={
            <PreviewState>
              <Compare />
            </PreviewState>
          }
        />
        <Route
          path="models"
          element={
            <PreviewState>
              <Models />
            </PreviewState>
          }
        />
        <Route
          path="reports"
          element={
            <PreviewState>
              <Reports />
            </PreviewState>
          }
        />
        <Route
          path="methodology"
          element={
            <PreviewState>
              <Methodology />
            </PreviewState>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>

      <Route
        path="admin/*"
        element={
          <Suspense
            fallback={
              <div className="admin-main">
                <Skeleton label="Loading admin console" />
              </div>
            }
          >
            <AdminSection />
          </Suspense>
        }
      />
    </Routes>
  );
}

export function App() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
