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
  const { demoExperiments, demoModels } = useDemoData();
  const worker = useWorkerHeartbeatQuery();
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
          value="6"
          detail="3 completed · 1 running · 1 queued · 1 failed"
          icon={FlaskConical}
        />
        <MetricCard
          label="Registered models"
          value="3"
          detail="Small language models · 2B–3B"
          icon={Boxes}
        />
        <MetricCard
          label="Illustrative decode rate"
          value="41.2"
          unit="tok/s"
          detail="Llama 3.2 · synthetic warm-run fixture"
          icon={Gauge}
        />
        <MetricCard
          label="Demo reports"
          value="3"
          detail="Reviewable examples, ready to explore"
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
                  Illustrative decode throughput · higher is faster
                </p>
              </div>
              <span className="subtle-tag">DEMO DATA</span>
            </div>
            <div className="mb-5 flex flex-wrap gap-2">
              <span className="chart-chip">Warm inference</span>
              <span className="chart-chip">Q4_K_M</span>
              <span className="chart-chip">Concurrency 1</span>
            </div>
            <div
              className="space-y-5"
              role="img"
              aria-label="Synthetic throughput: Llama 3.2 41.2 tokens per second, Qwen 2.5 36.8, Gemma 2 32.4. These are demo values, not a fair measured model ranking."
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
                      style={{ width: `${(model.throughput ?? 0) * 2}%`, background: model.color }}
                    />
                  </div>
                  <span className="text-right font-mono text-xs">
                    {model.throughput?.toFixed(1) ?? 'Unavailable'}
                  </span>
                </div>
              ))}
              <div className="ml-[102px] mr-[60px] flex justify-between font-mono text-[10px] text-muted-foreground">
                {[0, 10, 20, 30, 40, 50].map((value) => (
                  <span key={value}>{value}</span>
                ))}
              </div>
            </div>
            <p className="mt-5 text-[11px] leading-5 text-muted-foreground">
              Synthetic chart for interface review. Different models are not an equivalent baseline.
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
              Example hardware context. No device is connected.
            </p>
            <dl className="environment-list">
              <div>
                <dt>Accelerator</dt>
                <dd>NVIDIA RTX 4060</dd>
              </div>
              <div>
                <dt>GPU memory</dt>
                <dd>8 GB</dd>
              </div>
              <div>
                <dt>Inference engine</dt>
                <dd>Ollama</dd>
              </div>
              <div>
                <dt>Execution</dt>
                <dd className="text-slate-600">
                  {worker.data?.state === 'complete'
                    ? `${worker.data.data.availability} (demo)`
                    : 'Unavailable (demo)'}
                </dd>
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
              A snapshot of the synthetic experiment history.
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
          <span>Fixed example workload · no live measurements</span>
          <span className="ml-auto font-mono">4 of 6 runs</span>
        </div>
      </section>
    </>
  );
}
