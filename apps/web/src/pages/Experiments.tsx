import { useState } from 'react';
import { Search, X } from 'lucide-react';
import { PageHeading } from '@/components/PageHeading';
import { ExperimentTable } from '@/components/ExperimentTable';
import { EmptyState } from '@/components/EmptyState';
import { Button } from '@/components/ui/button';
import { useDemoData } from '@/api/hooks';

export function Experiments() {
  const { demoExperiments, dataLabel } = useDemoData();
  const [search, setSearch] = useState('');
  const [status, setStatus] = useState('');
  const rows = demoExperiments.filter(
    (row) =>
      `${row.name} ${row.model} ${row.id}`.toLowerCase().includes(search.toLowerCase()) &&
      (!status || row.status === status),
  );
  return (
    <>
      <PageHeading
        eyebrow="EXPERIMENT WORKSPACE"
        title="Experiments"
        description={
          dataLabel === 'DEMO DATA'
            ? 'Inspect configurations and lifecycle states in a read-only, synthetic experiment history.'
            : 'Inspect the configurations and accepted runs in this read-only published snapshot.'
        }
      />
      <div className="mb-6 flex items-start gap-3 rounded-lg border border-slate-200 bg-slate-100 px-4 py-3 text-xs leading-5 text-slate-600">
        <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-slate-500" />
        <p>
          {dataLabel === 'DEMO DATA'
            ? 'Experiment submission is unavailable in this preview. Only the authenticated admin will be able to queue local runs.'
            : 'This is a published static snapshot. Experiment submission and live job control remain unavailable.'}
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
              {[
                ['', 'All statuses'],
                ['complete', 'Completed'],
                ['running', 'Running'],
                ['pending', 'Pending'],
                ['failed', 'Failed'],
                ['cancelled', 'Cancelled'],
                ['unavailable', 'Unavailable'],
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
            {rows.length} {dataLabel === 'DEMO DATA' ? 'demo' : 'published'} experiments
          </span>
        </div>
        {rows.length ? (
          <ExperimentTable rows={rows} />
        ) : (
          <EmptyState
            onReset={() => {
              setSearch('');
              setStatus('');
            }}
          />
        )}
        <div className="table-footer">{dataLabel} · No jobs are being executed.</div>
      </section>
    </>
  );
}
