import {
  ArrowRight,
  ArrowUpRight,
  Boxes,
  FileChartColumn,
  FlaskConical,
  Gauge,
  SlidersHorizontal,
  Cpu,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { PageHeading } from '@/components/PageHeading';
import { MetricCard } from '@/components/MetricCard';
import { ExperimentTable } from '@/components/ExperimentTable';
import { useDemoData } from '@/api/hooks';
import { useWorkerHeartbeatQuery } from '@/api/hooks';

export function Overview() {
  const { demoExperiments, demoModels, demoReports, dataLabel, snapshot } = useDemoData();
  const worker = useWorkerHeartbeatQuery();
  const count = (state: string) => demoExperiments.filter((row) => row.status === state).length;
  const statusDetail =
    (
      [
        ['complete', 'completed'],
        ['running', 'running'],
        ['pending', 'queued'],
        ['failed', 'failed'],
        ['cancelled', 'cancelled'],
        ['unavailable', 'unavailable'],
      ] as const
    )
      .map(([state, label]) => (count(state) ? `${count(state)} ${label}` : null))
      .filter((value): value is string => value !== null)
      .join(' · ') || 'No published experiments';
  const decodeModel = demoModels.find(
    (model) => model.measurements.decodeThroughput.value !== null,
  );
  const decodeValue = decodeModel?.measurements.decodeThroughput.value ?? null;
  const maxDecode = Math.max(
    50,
    ...demoModels.map((model) => model.measurements.decodeThroughput.value ?? 0),
  );
  const chartTicks = Array.from({ length: 6 }, (_, index) => Math.round((maxDecode / 5) * index));
  const chartSummary =
    demoModels
      .map(
        (model) =>
          `${model.name} ${model.measurements.decodeThroughput.value?.toFixed(1) ?? 'unavailable'}`,
      )
      .join(', ') || 'no published models';
  const firstModel = demoModels[0];
  const hardware = firstModel?.hardware;
  const execution =
    snapshot.status === 'snapshot'
      ? 'Published snapshot'
      : worker.data?.state === 'complete'
        ? `${worker.data.data.availability} (demo)`
        : 'Unavailable (demo)';
  return (
    <>
      <PageHeading
        eyebrow="YOUR INFERENCE WORKSPACE"
        title="A clearer view of performance."
        description="Explore experiments, compare model behavior, and understand what happens between prompt and token."
        action={
          <Button asChild>
            <Link to="/experiments">
              Explore experiments <ArrowUpRight size={15} aria-hidden="true" />
            </Link>
          </Button>
        }
      />
      <div className="mb-7 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Experiment runs"
          value={String(demoExperiments.length)}
          detail={statusDetail}
          icon={FlaskConical}
        />
        <MetricCard
          label="Registered models"
          value={String(demoModels.length)}
          detail={
            [...new Set(demoModels.map((model) => model.size))].join(' · ') || 'No published models'
          }
          icon={Boxes}
        />
        <MetricCard
          label={dataLabel === 'DEMO DATA' ? 'Illustrative decode rate' : 'Published decode rate'}
          value={decodeValue === null ? 'Unavailable' : decodeValue.toFixed(1)}
          {...(decodeValue === null ? {} : { unit: 'tok/s' })}
          detail={`${decodeModel?.name ?? 'No published model'} · ${
            dataLabel === 'DEMO DATA' ? 'synthetic warm-run fixture' : 'published snapshot'
          }`}
          icon={Gauge}
        />
        <MetricCard
          label={dataLabel === 'DEMO DATA' ? 'Demo reports' : 'Published reports'}
          value={String(demoReports.length)}
          detail={
            dataLabel === 'DEMO DATA'
              ? 'Reviewable examples, ready to explore'
              : 'Reviewed static report snapshots'
          }
          icon={FileChartColumn}
        />
      </div>
      <div className="mb-7 grid gap-5 xl:grid-cols-[1.65fr_1fr]">
        <Card className="shadow-none">
          <CardContent className="p-6">
            <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="section-title">Model performance at a glance</h2>
                <p className="mt-1 text-xs text-muted-foreground">
                  {dataLabel === 'DEMO DATA' ? 'Illustrative' : 'Published'} decode throughput ·
                  higher is faster
                </p>
              </div>
              <span className="subtle-tag">{dataLabel}</span>
            </div>
            <div className="mb-5 flex flex-wrap gap-2">
              <span className="chart-chip">{firstModel?.condition ?? 'Condition unavailable'}</span>
              <span className="chart-chip">
                {firstModel?.quantization ?? 'Quantization unavailable'}
              </span>
              <span className="chart-chip">
                Concurrency {firstModel?.concurrency ?? 'unavailable'}
              </span>
            </div>
            <div
              className="space-y-5"
              role="img"
              aria-label={`${
                dataLabel === 'DEMO DATA' ? 'Synthetic' : 'Published'
              } throughput: ${chartSummary}. ${
                dataLabel === 'DEMO DATA'
                  ? 'These are demo values, not a fair measured model ranking.'
                  : 'Read the attached context before comparing models.'
              }`}
            >
              {demoModels.map((model) => (
                <div key={model.id} className="grid grid-cols-[90px_1fr_48px] items-center gap-3">
                  <span className="text-xs font-medium">
                    {model.name}
                    <span className="ml-1 text-muted-foreground">{model.size}</span>
                  </span>
                  <div className="bar-track">
                    <div
                      className="bar"
                      style={{
                        width: `${
                          ((model.measurements.decodeThroughput.value ?? 0) / maxDecode) * 100
                        }%`,
                        background: model.color,
                      }}
                    />
                  </div>
                  <span className="text-right font-mono text-xs">
                    {model.measurements.decodeThroughput.value?.toFixed(1) ?? 'Unavailable'}
                  </span>
                </div>
              ))}
              <div className="ml-[102px] mr-[60px] flex justify-between font-mono text-[10px] text-muted-foreground">
                {chartTicks.map((value) => (
                  <span key={value}>{value}</span>
                ))}
              </div>
            </div>
            <p className="mt-5 text-[11px] leading-5 text-muted-foreground">
              {dataLabel === 'DEMO DATA'
                ? 'Synthetic chart for interface review. Different models are not an equivalent baseline.'
                : 'Published snapshot values. Different models and conditions are not an equivalent baseline.'}
            </p>
          </CardContent>
        </Card>
        <Card className="environment-card shadow-none">
          <CardContent className="p-6">
            <div className="flex items-center gap-2">
              <Cpu size={17} className="text-primary" aria-hidden="true" />
              <h2 className="section-title">The local lab</h2>
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {dataLabel === 'DEMO DATA'
                ? 'Example hardware context. No device is connected.'
                : 'Hardware context from the published snapshot. No device is connected.'}
            </p>
            <dl className="environment-list">
              <div>
                <dt>Accelerator</dt>
                <dd>{hardware?.deviceName ?? 'Unavailable'}</dd>
              </div>
              <div>
                <dt>GPU memory</dt>
                <dd>
                  {hardware?.deviceMemoryMib === null || hardware?.deviceMemoryMib === undefined
                    ? 'Unavailable'
                    : `${hardware.deviceMemoryMib} MiB`}
                </dd>
              </div>
              <div>
                <dt>Inference engine</dt>
                <dd>{firstModel?.provenance?.engine.name ?? 'Unavailable'}</dd>
              </div>
              <div>
                <dt>Execution</dt>
                <dd className="text-slate-600">{execution}</dd>
              </div>
            </dl>
            <Link to="/methodology" className="inline-link">
              How we measure <ArrowRight size={14} aria-hidden="true" />
            </Link>
          </CardContent>
        </Card>
      </div>
      <section className="rounded-xl border bg-white">
        <div className="panel-header">
          <div>
            <h2 className="section-title">Recent experiments</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              {dataLabel === 'DEMO DATA'
                ? 'A snapshot of the synthetic experiment history.'
                : 'A snapshot of the published experiment history.'}
            </p>
          </div>
          <Button variant="ghost" size="sm" asChild>
            <Link to="/experiments">
              View all <ArrowRight aria-hidden="true" />
            </Link>
          </Button>
        </div>
        <ExperimentTable rows={demoExperiments.slice(0, 4)} />
        <div className="table-footer">
          <SlidersHorizontal size={13} aria-hidden="true" />
          <span>
            {dataLabel === 'DEMO DATA'
              ? 'Fixed example workload · no live measurements'
              : 'Published snapshot · no live measurements'}
          </span>
          <span className="ml-auto font-mono">
            {Math.min(4, demoExperiments.length)} of {demoExperiments.length} runs
          </span>
        </div>
      </section>
    </>
  );
}
