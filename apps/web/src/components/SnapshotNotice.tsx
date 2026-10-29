import { CalendarClock, Info, TriangleAlert } from 'lucide-react';
import { useSnapshotInfo } from '@/api/snapshot-context';

function formatSnapshotDate(value: string) {
  return new Intl.DateTimeFormat('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(value));
}

export function SnapshotNotice() {
  const snapshot = useSnapshotInfo();
  if (snapshot.status === 'snapshot' && snapshot.publishedAt) {
    return (
      <div className="demo-notice snapshot-notice">
        <CalendarClock size={15} className="shrink-0" aria-hidden="true" />
        <p>
          <strong>Published snapshot.</strong> Results as of{' '}
          <time dateTime={snapshot.publishedAt}>{formatSnapshotDate(snapshot.publishedAt)}</time>.
          Release <span className="font-mono">{snapshot.releaseId}</span>. Served as static reviewed
          data; no backend or GPU is connected.
        </p>
      </div>
    );
  }
  if (snapshot.status === 'error') {
    return (
      <div role="alert" className="demo-notice snapshot-notice snapshot-notice-error">
        <TriangleAlert size={15} className="shrink-0" aria-hidden="true" />
        <p>
          <strong>Published snapshot unavailable.</strong> {snapshot.error} Showing bundled demo
          data; no results were published from this browser.
        </p>
      </div>
    );
  }
  return (
    <div className="demo-notice">
      <Info size={15} className="shrink-0" aria-hidden="true" />
      <p>
        <strong>Demo workspace.</strong> All results and statuses are synthetic UI fixtures. No
        backend or GPU is connected.
      </p>
    </div>
  );
}
