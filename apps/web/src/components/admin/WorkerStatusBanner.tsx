import { CircleAlert, CircleCheck, CircleHelp, LoaderCircle, PauseCircle } from 'lucide-react';
import { friendlyApiMessage } from '@/api/client';
import { useWorkerQuery } from '@/admin/queries';
import { formatDateTime } from '@/admin/format';
import { Button } from '@/components/ui/button';

export function WorkerStatusBanner() {
  const worker = useWorkerQuery();

  if (worker.isPending && !worker.data) {
    return (
      <div className="worker-banner" role="status">
        <LoaderCircle size={18} className="animate-spin" aria-hidden="true" />
        <div>
          <p className="font-medium">Checking worker availability…</p>
          <p>Queued work is not started until the local worker is online.</p>
        </div>
      </div>
    );
  }

  if (worker.error && !worker.data) {
    return (
      <div className="worker-banner worker-banner-warning" role="status">
        <CircleAlert size={18} aria-hidden="true" />
        <div className="flex-1">
          <p className="font-medium">Worker status unavailable</p>
          <p>{friendlyApiMessage(worker.error)}</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => void worker.refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (!worker.data) return null;
  const status = worker.data;

  if (status.paused) {
    return (
      <div className="worker-banner worker-banner-warning" role="status">
        <PauseCircle size={18} aria-hidden="true" />
        <div>
          <p className="font-medium">Worker paused</p>
          <p>
            New jobs will not start until an operator resumes the queue. Last heartbeat:{' '}
            {formatDateTime(status.last_seen_at)}.
          </p>
        </div>
      </div>
    );
  }

  if (status.availability === 'unknown') {
    return (
      <div className="worker-banner worker-banner-warning" role="status">
        <CircleHelp size={18} aria-hidden="true" />
        <div>
          <p className="font-medium">Worker has not reported a heartbeat</p>
          <p>Submissions may queue, but no start time is guaranteed until a worker connects.</p>
        </div>
      </div>
    );
  }

  if (status.availability === 'offline') {
    return (
      <div className="worker-banner worker-banner-offline" role="status">
        <CircleAlert size={18} aria-hidden="true" />
        <div>
          <p className="font-medium">Worker offline</p>
          <p>
            Last heartbeat {formatDateTime(status.last_seen_at)}. Queued jobs will wait; offline
            does not mean a job failed.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="worker-banner worker-banner-online" role="status">
      <CircleCheck size={18} aria-hidden="true" />
      <div>
        <p className="font-medium">
          Worker online, {status.mode === 'running' ? 'running a job' : 'idle'}
        </p>
        <p>
          Last heartbeat {formatDateTime(status.last_seen_at)}
          {status.active_job_id ? ` · Active job ${status.active_job_id}` : ''}.
        </p>
      </div>
    </div>
  );
}
