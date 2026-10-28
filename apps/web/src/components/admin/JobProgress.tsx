import { Check, Circle, CircleAlert, CircleSlash, Clock3 } from 'lucide-react';
import type { Job } from '@/api/types';
import { formatDateTime, jobErrorMessages } from '@/admin/format';
import { StatusBadge } from '@/components/StatusBadge';

const phaseIndex = {
  queued: 0,
  leased: 1,
  running: 2,
  completed: 3,
  failed: 3,
  cancelled: 3,
} as const;

export function JobProgress({ job }: { job: Job }) {
  const steps = [
    { label: 'Queued', detail: 'Accepted into the durable local queue.' },
    { label: 'Leased', detail: 'The worker reserved the job with a fenced lease.' },
    { label: 'Running', detail: 'Inference execution is in progress.' },
    job.phase === 'failed'
      ? { label: 'Failed', detail: 'The server recorded a failed terminal state.' }
      : job.phase === 'cancelled'
        ? { label: 'Cancelled', detail: 'The server recorded a cancelled terminal state.' }
        : { label: 'Completed', detail: 'The server confirmed the completed terminal state.' },
  ];
  const current = phaseIndex[job.phase];
  const terminal = job.phase === 'failed' || job.phase === 'cancelled';

  return (
    <section aria-labelledby="job-progress-heading" className="admin-card">
      <div className="admin-card-header">
        <div>
          <h2 id="job-progress-heading" className="section-title">
            Job progress
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Server-confirmed state. A queued or running job is not a completed result.
          </p>
        </div>
        <StatusBadge status={job.state} />
      </div>
      <div className="p-5">
        <ol className="job-timeline">
          {steps.map((step, index) => {
            const state = index < current ? 'done' : index === current ? 'current' : 'upcoming';
            return (
              <li
                key={step.label}
                className={`job-timeline-step ${state}`}
                aria-current={state === 'current' ? 'step' : undefined}
              >
                <span className="job-timeline-marker" aria-hidden="true">
                  {state === 'done' ? <Check size={13} /> : <Circle size={12} />}
                </span>
                <div>
                  <p className="font-medium">{step.label}</p>
                  <p className="text-xs text-muted-foreground">{step.detail}</p>
                </div>
              </li>
            );
          })}
        </ol>

        <dl className="mt-5 grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-xs text-muted-foreground">Phase</dt>
            <dd className="font-mono text-xs">{job.phase}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Attempt</dt>
            <dd className="font-mono text-xs">{job.attempt}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Queued at</dt>
            <dd>{formatDateTime(job.created_at)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Started at</dt>
            <dd>{formatDateTime(job.started_at)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Finished at</dt>
            <dd>{formatDateTime(job.finished_at)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Job ID</dt>
            <dd className="font-mono text-xs">{job.id}</dd>
          </div>
        </dl>

        {job.cancellation_requested && !terminal && (
          <div className="admin-inline-alert mt-4" role="status">
            <Clock3 size={16} aria-hidden="true" />
            <p>
              Cancellation requested. The worker has not acknowledged it yet; execution may still be
              stopping.
            </p>
          </div>
        )}

        {job.error_code && (
          <div className="admin-inline-alert admin-inline-alert-error mt-4" role="alert">
            <CircleAlert size={16} aria-hidden="true" />
            <p>
              <strong>{job.error_code}</strong>: {jobErrorMessages[job.error_code]}
            </p>
          </div>
        )}

        {job.phase === 'cancelled' && (
          <p className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
            <CircleSlash size={14} aria-hidden="true" />
            Cancelled jobs are excluded from successful aggregates.
          </p>
        )}
      </div>
    </section>
  );
}
