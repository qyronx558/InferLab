import { Navigate, Route, Routes } from 'react-router-dom';
import { LiveQueryProvider } from '@/api/LiveQueryProvider';
import { AdminShell } from '@/components/admin/AdminShell';
import { NotFound } from '@/pages/NotFound';
import { AdminLogin } from '@/pages/admin/AdminLogin';
import { ExperimentDetail } from '@/pages/admin/ExperimentDetail';
import { ExperimentList } from '@/pages/admin/ExperimentList';
import { NewExperiment } from '@/pages/admin/NewExperiment';
import { AuthProvider, RequireAdmin } from './auth';

export default function AdminSection() {
  return (
    <LiveQueryProvider>
      <AuthProvider>
        <Routes>
          <Route path="login" element={<AdminLogin />} />
          <Route
            element={
              <RequireAdmin>
                <AdminShell />
              </RequireAdmin>
            }
          >
            <Route index element={<Navigate to="/admin/experiments" replace />} />
            <Route path="experiments" element={<ExperimentList />} />
            <Route path="experiments/new" element={<NewExperiment />} />
            <Route path="experiments/:id" element={<ExperimentDetail />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </AuthProvider>
    </LiveQueryProvider>
  );
}
