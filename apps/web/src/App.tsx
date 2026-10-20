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

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
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
