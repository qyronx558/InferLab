import { useState } from 'react';
import { Search, X } from 'lucide-react';
import { PageHeading } from '@/components/PageHeading';
import { ExperimentTable } from '@/components/ExperimentTable';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { demoExperiments } from '@/data/demo';

export function Experiments() {
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('All statuses');
  const rows = demoExperiments.filter(
    (row) =>
      `${row.name} ${row.model} ${row.id}`.toLowerCase().includes(search.toLowerCase()) &&
      (status === 'All statuses' || row.status === status),
  );
  return (
    <>
      <PageHeading
        eyebrow="EXPERIMENT WORKSPACE"
        title="Experiments"
        description="Inspect configurations and lifecycle states in a read-only, synthetic experiment history."
      />
      <div className="mb-6 flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-100 px-4 py-3 text-xs leading-5 text-slate-600">
        <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-slate-500" />
        <p>
          Experiment submission is unavailable in this preview. Only the authenticated admin will be
          able to queue local runs.
        </p>
      </div>
      <section className="overflow-hidden rounded-xl border bg-white">
        <div className="filter-bar">
          <label className="search-field">
            <Search size={16} aria-hidden="true" />
            <span className="sr-only">Search experiments</span>
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search experiments or models…"
            />
          </label>
          <label>
            <span className="sr-only">Filter by status</span>
            <select
              className="native-select"
              value={status}
              onChange={(e) => setStatus(e.target.value)}
            >
              {['All statuses', 'Completed', 'Running', 'Queued', 'Failed'].map((value) => (
                <option key={value}>{value}</option>
              ))}
            </select>
          </label>
          {(search || status !== 'All statuses') && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setSearch('');
                setStatus('All statuses');
              }}
            >
              <X size={14} aria-hidden="true" />
              Clear
            </Button>
          )}
          <span role="status" className="ml-auto text-xs text-muted-foreground">
            {rows.length} demo experiments
          </span>
        </div>
        {rows.length ? (
          <ExperimentTable rows={rows} />
        ) : (
          <EmptyState
            onReset={() => {
              setSearch('');
              setStatus('All statuses');
            }}
          />
        )}
        <div className="table-footer">DEMO DATA · No jobs are being executed.</div>
      </section>
    </>
  );
}
