import { ArrowLeft, PauseCircle, RefreshCcw, RotateCcw, Trash2 } from 'lucide-react';
import { useRef, useState, type FormEvent } from 'react';
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom';
import { friendlyApiMessage } from '@/api/client';
import { formatDateTime, formatNumber } from '@/admin/format';
import {
  newIdempotencyKey,
  useArchiveExperiment,
  useCancelExperiment,
  useExperimentQuery,
  useRenameExperiment,
  useRetryExperiment,
} from '@/admin/queries';
import { PageHeading } from '@/components/PageHeading';
import { ErrorState } from '@/components/ErrorState';
import { Skeleton } from '@/components/Skeleton';
import { JobProgress } from '@/components/admin/JobProgress';
import { WorkerStatusBanner } from '@/components/admin/WorkerStatusBanner';
import { Button } from '@/components/ui/button';

function ConfigSummary({
  experiment,
}: {
  experiment: NonNullable<ReturnType<typeof useExperimentQuery>['data']>;
}) {
  const { config } = experiment;
  return (
    <section className="admin-card" aria-labelledby="config-heading">
      <div className="admin-card-header">
        <div>
          <h2 id="config-heading" className="section-title">
            Immutable configuration
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Pins and bounds accepted by the local runner. The configuration cannot be edited after
            queueing.
          </p>
        </div>
      </div>
      <div className="p-5">
        <div className="config-grid">
          <dl>
            <h3>Engine</h3>
            <dt>ID</dt>
            <dd>{config.engine_id}</dd>
            <dt>Version</dt>
            <dd>{config.engine_version}</dd>
            <dt>Build</dt>
            <dd>{config.engine_build}</dd>
            <dt>Seed support</dt>
            <dd>{config.seed_supported ? 'Supported' : 'Not supported'}</dd>
          </dl>
          <dl>
            <h3>Model</h3>
            <dt>ID</dt>
            <dd>{config.model_id}</dd>
            <dt>Revision</dt>
            <dd>{config.model_revision}</dd>
            <dt>Quantization</dt>
            <dd>{config.quantization}</dd>
            <dt>SHA-256</dt>
            <dd className="break-all font-mono text-[11px]">{config.model_sha256}</dd>
          </dl>
          <dl>
            <h3>Workload</h3>
            <dt>Workload ID</dt>
            <dd>{config.workload_id}</dd>
            <dt>Prompt ID</dt>
            <dd>{config.prompt_id}</dd>
            <dt>Condition</dt>
            <dd>{config.condition}</dd>
          </dl>
          <dl>
            <h3>Token budgets</h3>
            <dt>Context</dt>
            <dd>{config.context_tokens.toLocaleString()} tokens</dd>
            <dt>Input budget</dt>
            <dd>{config.input_token_budget.toLocaleString()} tokens</dd>
            <dt>Max output</dt>
            <dd>{config.max_output_tokens.toLocaleString()} tokens</dd>
          </dl>
          <dl>
            <h3>Sampling</h3>
            <dt>Temperature</dt>
            <dd>{formatNumber(config.sampling.temperature, 2)}</dd>
            <dt>Top-p</dt>
            <dd>{formatNumber(config.sampling.top_p, 2)}</dd>
            <dt>Seed</dt>
            <dd>{config.sampling.seed ?? 'Not set'}</dd>
          </dl>
          <dl>
            <h3>Execution</h3>
            <dt>Warmups</dt>
            <dd>{config.warmups} runs</dd>
            <dt>Repetitions</dt>
            <dd>{config.repetitions} measured runs</dd>
            <dt>Concurrency</dt>
            <dd>{config.concurrency} run at a time</dd>
            <dt>Timeout</dt>
            <dd>{config.timeout_seconds} seconds</dd>
          </dl>
          <dl>
            <h3>Hardware</h3>
            <dt>GPU device</dt>
            <dd>{config.gpu_device_id}</dd>
            <dt>GPU layers</dt>
            <dd>{config.gpu_layers ?? 'Runner default'}</dd>
          </dl>
        </div>
      </div>
    </section>
  );
}

export function ExperimentDetail() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const experiment = useExperimentQuery(id);
  const rename = useRenameExperiment();
  const cancel = useCancelExperiment();
  const retry = useRetryExperiment();
  const archive = useArchiveExperiment();

  const [renameOpen, setRenameOpen] = useState(false);
  const [name, setName] = useState('');
  const [renameError, setRenameError] = useState<string | null>(null);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const renameKey = useRef<string | null>(null);
  const cancelKey = useRef<string | null>(null);
  const retryKey = useRef<string | null>(null);
  const archiveKey = useRef<string | null>(null);

  if (experiment.isPending) return <Skeleton label="Loading experiment" />;

  if (experiment.error && !experiment.data) {
    const notFound =
      typeof experiment.error === 'object' &&
      experiment.error !== null &&
      'status' in experiment.error &&
      experiment.error.status === 404;
    return (
      <ErrorState
        onRetry={() => navigate('/admin/experiments')}
        title={notFound ? 'Experiment not found' : 'Unable to load experiment'}
        description={
          notFound
            ? 'The record may have been archived or the ID is incorrect.'
            : friendlyApiMessage(experiment.error)
        }
        actionLabel={notFound ? 'Back to experiments' : 'Retry'}
      />
    );
  }

  const data = experiment.data;
  const { job } = data;
  const active = job.phase === 'queued' || job.phase === 'leased' || job.phase === 'running';
  const cancellable =
    (job.phase === 'queued' || job.phase === 'leased' || job.phase === 'running') &&
    !job.cancellation_requested;
  const retryable = job.phase === 'failed' || job.phase === 'cancelled';
  const archivable = job.phase !== 'leased' && job.phase !== 'running';
  const created = (location.state as { created?: unknown } | null)?.created === true;

  const startRename = () => {
    setRenameOpen(true);
    setName(data.name);
    setRenameError(null);
    renameKey.current = null;
  };

  const submitRename = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setRenameError('Enter an administrative name.');
      return;
    }
    if (trimmed.length > 160) {
      setRenameError('Use 160 characters or fewer.');
      return;
    }
    renameKey.current ??= newIdempotencyKey();
    setRenameError(null);
    setActionError(null);
    rename.mutate(
      { id: data.id, name: trimmed, version: data.version, key: renameKey.current },
      {
        onSuccess: () => {
          setRenameOpen(false);
          renameKey.current = null;
        },
        onError: (error) => setRenameError(friendlyApiMessage(error)),
      },
    );
  };

  return (
    <>
      <title>{data.name} · InferLab Admin</title>
      <Link className="admin-back-link" to="/admin/experiments">
        <ArrowLeft size={14} aria-hidden="true" />
        All experiments
      </Link>
      <PageHeading
        eyebrow="EXPERIMENT DETAIL"
        title={data.name}
        description={`${data.id} · administrative version ${data.version} · created ${formatDateTime(job.created_at)}`}
        titleSuffix="InferLab admin"
        action={
          <Button asChild variant="outline">
            <Link to="/admin/experiments/new">New experiment</Link>
          </Button>
        }
      />
      <WorkerStatusBanner />

      {created && job.state === 'pending' && (
        <div className="admin-inline-alert mb-5" role="status">
          <p>
            <strong>Submission accepted.</strong> The job is queued; it has not started. This page
            polls the API for server-confirmed progress.
          </p>
        </div>
      )}

      {actionError && (
        <div className="admin-form-error mb-5" role="alert">
          <p>{actionError}</p>
        </div>
      )}

      <div className="admin-detail-grid">
        <div className="space-y-5">
          <JobProgress job={job} />
          <ConfigSummary experiment={data} />
        </div>

        <aside className="space-y-5" aria-label="Experiment actions">
          <section className="admin-card">
            <div className="admin-card-header">
              <h2 className="section-title">Administrative actions</h2>
            </div>
            <div className="space-y-3 p-5">
              {!renameOpen ? (
                <Button variant="outline" className="w-full justify-start" onClick={startRename}>
                  Rename
                </Button>
              ) : (
                <form onSubmit={submitRename} noValidate className="space-y-3">
                  <div className="admin-field">
                    <label htmlFor="experiment-name" className="admin-field-label">
                      Administrative name
                    </label>
                    <input
                      id="experiment-name"
                      className="admin-input"
                      value={name}
                      maxLength={160}
                      onChange={(event) => {
                        setName(event.target.value);
                        renameKey.current = null;
                        setRenameError(null);
                      }}
                      aria-invalid={renameError ? true : undefined}
                      aria-describedby={renameError ? 'experiment-name-error' : undefined}
                    />
                    {renameError && (
                      <p id="experiment-name-error" className="admin-field-error">
                        {renameError}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2">
                    <Button type="submit" size="sm" disabled={rename.isPending}>
                      {rename.isPending ? 'Saving…' : 'Save name'}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setRenameOpen(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                </form>
              )}

              {cancellable && (
                <Button
                  variant="outline"
                  className="w-full justify-start"
                  disabled={cancel.isPending}
                  onClick={() => {
                    cancelKey.current ??= newIdempotencyKey();
                    setActionError(null);
                    cancel.mutate(
                      { id: data.id, key: cancelKey.current },
                      {
                        onError: (error) => setActionError(friendlyApiMessage(error)),
                        onSuccess: () => {
                          cancelKey.current = null;
                        },
                      },
                    );
                  }}
                >
                  <PauseCircle size={15} aria-hidden="true" />
                  {cancel.isPending ? 'Requesting cancellation…' : 'Cancel job'}
                </Button>
              )}
              {job.cancellation_requested && active && (
                <p className="text-xs text-muted-foreground" role="status">
                  Cancellation requested. Waiting for worker acknowledgement.
                </p>
              )}

              {retryable && (
                <Button
                  variant="outline"
                  className="w-full justify-start"
                  disabled={retry.isPending}
                  onClick={() => {
                    retryKey.current ??= newIdempotencyKey();
                    setActionError(null);
                    retry.mutate(
                      { id: data.id, key: retryKey.current },
                      {
                        onError: (error) => setActionError(friendlyApiMessage(error)),
                        onSuccess: () => {
                          retryKey.current = null;
                        },
                      },
                    );
                  }}
                >
                  <RotateCcw size={15} aria-hidden="true" />
                  {retry.isPending ? 'Queueing retry…' : 'Retry as a new job'}
                </Button>
              )}

              {archivable && !confirmArchive && (
                <Button
                  variant="outline"
                  className="w-full justify-start text-destructive"
                  onClick={() => setConfirmArchive(true)}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  Archive experiment
                </Button>
              )}
              {confirmArchive && (
                <div className="admin-confirm" role="alertdialog" aria-labelledby="archive-title">
                  <p id="archive-title" className="font-medium">
                    Archive this experiment?
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {job.phase === 'queued'
                      ? 'The queued job will be cancelled. Evidence remains reserved and published reports are unchanged.'
                      : 'The private record will be hidden. Published reports are unchanged.'}
                  </p>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="destructive"
                      disabled={archive.isPending}
                      onClick={() => {
                        archiveKey.current ??= newIdempotencyKey();
                        setActionError(null);
                        archive.mutate(
                          {
                            id: data.id,
                            version: data.version,
                            key: archiveKey.current,
                          },
                          {
                            onError: (error) => setActionError(friendlyApiMessage(error)),
                            onSuccess: () => navigate('/admin/experiments'),
                          },
                        );
                      }}
                    >
                      {archive.isPending ? 'Archiving…' : 'Confirm archive'}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setConfirmArchive(false)}>
                      Keep experiment
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </section>

          <section className="admin-card p-5">
            <h2 className="section-title">Safety notes</h2>
            <ul className="mt-3 space-y-2 text-xs leading-5 text-muted-foreground">
              <li>Actions use the CSRF token from the current server-side session.</li>
              <li>Cancel is a request; it is not confirmed until the worker acknowledges it.</li>
              <li>Retry creates a new queued job and keeps the previous attempt as evidence.</li>
              <li>
                <RefreshCcw size={12} className="mr-1 inline" aria-hidden="true" />
                Progress is polled every 5 seconds while the job is queued or running.
              </li>
            </ul>
          </section>
        </aside>
      </div>
    </>
  );
}
