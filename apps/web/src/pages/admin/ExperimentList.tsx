import { ArrowUpRight, Plus, Search, X } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { friendlyApiMessage } from '@/api/client';
import { useExperimentsQuery } from '@/admin/queries';
import { formatDateTime } from '@/admin/format';
import { PageHeading } from '@/components/PageHeading';
import { WorkerStatusBanner } from '@/components/admin/WorkerStatusBanner';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { Skeleton } from '@/components/Skeleton';
import { StatusBadge } from '@/components/StatusBadge';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

export function ExperimentList() {
  const experiments = useExperimentsQuery();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');

  const items = experiments.data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = items.filter((experiment) => {
    const haystack =
      `${experiment.id} ${experiment.name} ${experiment.config.model_id} ${experiment.config.workload_id}`.toLowerCase();
    return (
      haystack.includes(search.trim().toLowerCase()) && (!status || experiment.job.state === status)
    );
  });

  return (
    <>
      <title>Experiments · InferLab Admin</title>
      <PageHeading
        eyebrow="LOCAL ADMIN"
        title="Experiments"
        description="Queue bounded local runs and follow server-confirmed job states. Submission acceptance is separate from execution and completion."
        titleSuffix="InferLab admin"
        action={
          <Button asChild>
            <Link to="/admin/experiments/new">
              <Plus size={15} aria-hidden="true" />
              New experiment
            </Link>
          </Button>
        }
      />
      <WorkerStatusBanner />

      {experiments.isPending ? (
        <Skeleton label="Loading experiments" />
      ) : experiments.error && !experiments.data ? (
        <ErrorState
          onRetry={() => void experiments.refetch()}
          title="Unable to load experiments"
          description={friendlyApiMessage(experiments.error)}
          actionLabel="Retry"
        />
      ) : (
        <section className="admin-card" aria-labelledby="experiment-list-heading">
          <h2 id="experiment-list-heading" className="sr-only">
            Experiment list
          </h2>
          <div className="filter-bar">
            <label className="search-field">
              <Search size={16} aria-hidden="true" />
              <span className="sr-only">Search experiments</span>
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search loaded experiments…"
              />
            </label>
            <label>
              <span className="sr-only">Filter by job status</span>
              <select
                className="native-select"
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                {[
                  ['', 'All statuses'],
                  ['pending', 'Queued / leased'],
                  ['running', 'Running'],
                  ['complete', 'Completed'],
                  ['failed', 'Failed'],
                  ['cancelled', 'Cancelled'],
                ].map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {(search || status) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSearch('');
                  setStatus('');
                }}
              >
                <X size={14} aria-hidden="true" />
                Clear
              </Button>
            )}
            <span role="status" className="ml-auto text-xs text-muted-foreground">
              {filtered.length} of {items.length} loaded
            </span>
          </div>

          {filtered.length ? (
            <div
              className="table-scroll"
              role="region"
              aria-label="Admin experiments table"
              tabIndex={0}
            >
              <Table>
                <TableCaption className="sr-only">
                  Local experiments with server-confirmed job state. Queued and running are not
                  completed.
                </TableCaption>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[30%]">Experiment</TableHead>
                    <TableHead>Model / workload</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Attempt</TableHead>
                    <TableHead className="text-right">Queued</TableHead>
                    <TableHead>
                      <span className="sr-only">Open details</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {filtered.map((experiment) => (
                    <TableRow key={experiment.id}>
                      <TableCell>
                        <Link
                          className="font-medium hover:text-primary hover:underline"
                          to={`/admin/experiments/${experiment.id}`}
                        >
                          {experiment.name}
                        </Link>
                        <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                          {experiment.id}
                        </p>
                      </TableCell>
                      <TableCell>
                        <p className="font-mono text-xs">{experiment.config.model_id}</p>
                        <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                          {experiment.config.workload_id}
                        </p>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={experiment.job.state} />
                        <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                          {experiment.job.phase}
                        </p>
                      </TableCell>
                      <TableCell className="text-right font-mono text-xs">
                        {experiment.job.attempt}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-right text-xs text-muted-foreground">
                        {formatDateTime(experiment.job.created_at)}
                      </TableCell>
                      <TableCell>
                        <Link
                          className="table-action"
                          to={`/admin/experiments/${experiment.id}`}
                          aria-label={`Open ${experiment.id}`}
                        >
                          <ArrowUpRight size={16} aria-hidden="true" />
                        </Link>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <EmptyState
              title={items.length ? 'No loaded experiments match' : 'No experiments yet'}
              description={
                items.length
                  ? 'Search and status filters apply to the loaded pages. Load more or clear the filters.'
                  : 'Queue a bounded experiment. It will stay queued until a local worker is online.'
              }
              action={
                items.length ? (
                  <Button
                    variant="outline"
                    onClick={() => {
                      setSearch('');
                      setStatus('');
                    }}
                  >
                    Clear filters
                  </Button>
                ) : (
                  <Button asChild>
                    <Link to="/admin/experiments/new">Queue the first experiment</Link>
                  </Button>
                )
              }
            />
          )}

          {experiments.hasNextPage && (
            <div className="table-footer">
              <Button
                variant="outline"
                size="sm"
                onClick={() => void experiments.fetchNextPage()}
                disabled={experiments.isFetchingNextPage}
              >
                {experiments.isFetchingNextPage ? 'Loading…' : 'Load more experiments'}
              </Button>
              <span>Search filters only the records already loaded.</span>
            </div>
          )}
        </section>
      )}
    </>
  );
}
