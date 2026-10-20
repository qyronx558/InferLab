import { ArrowRight, Fingerprint, Gauge, Layers3, ShieldCheck } from 'lucide-react';
import { Link } from 'react-router-dom';
import { PageHeading } from '@/components/PageHeading';
import { Card, CardContent } from '@/components/ui/card';

const principles = [
  {
    icon: Fingerprint,
    title: 'Reproducibility first',
    text: 'Pin the exact model revision, quantization, engine build, workload and device settings. Record every run with timestamps and units.',
  },
  {
    icon: Layers3,
    title: 'Separate warm and cold',
    text: 'Model loading and warmed inference describe different conditions. Keep warmups separate and report repeated measured samples.',
  },
  {
    icon: Gauge,
    title: 'Measure what users feel',
    text: 'Time to first token requires streaming. Show request latency, token counts, throughput, errors and sample sizes together.',
  },
  {
    icon: ShieldCheck,
    title: 'Honest comparisons',
    text: 'Hold workload, output budget, sampling and hardware conditions constant. Disclose changed variables and unavailable quality measurements.',
  },
];
export function Methodology() {
  return (
    <>
      <PageHeading
        eyebrow="THE MEASUREMENT PLAYBOOK"
        title="Context before conclusions."
        description="A practical framework for transparent, reproducible inference benchmarks. This page explains the intended method; the dashboard values remain DEMO DATA."
      />
      <div className="grid gap-5 md:grid-cols-2">
        {principles.map(({ icon: Icon, title, text }, index) => (
          <Card key={title} className="shadow-none">
            <CardContent className="p-6">
              <div className="mb-4 flex items-center justify-between">
                <Icon size={22} className="text-primary" aria-hidden="true" />
                <span className="font-mono text-xs text-slate-500">0{index + 1}</span>
              </div>
              <h2 className="text-base font-semibold">{title}</h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">{text}</p>
            </CardContent>
          </Card>
        ))}
      </div>
      <section className="mt-7 rounded-xl border bg-white p-6">
        <h2 className="section-title">Reading the metrics</h2>
        <dl className="mt-5 grid gap-6 sm:grid-cols-2">
          <div>
            <dt className="font-mono text-xs font-semibold text-primary">TTFT · milliseconds</dt>
            <dd className="mt-2 text-sm leading-6 text-muted-foreground">
              Elapsed client time from request start to the first streamed token. Lower is faster to
              begin responding.
            </dd>
          </div>
          <div>
            <dt className="font-mono text-xs font-semibold text-primary">
              Decode rate · tokens/second
            </dt>
            <dd className="mt-2 text-sm leading-6 text-muted-foreground">
              Output generation speed under documented conditions. Tokenization and output length
              affect comparability.
            </dd>
          </div>
          <div>
            <dt className="font-mono text-xs font-semibold text-primary">
              Request latency · milliseconds
            </dt>
            <dd className="mt-2 text-sm leading-6 text-muted-foreground">
              Time to complete the entire request. Tail percentiles require adequate samples and a
              stated protocol.
            </dd>
          </div>
          <div>
            <dt className="font-mono text-xs font-semibold text-primary">VRAM · gigabytes</dt>
            <dd className="mt-2 text-sm leading-6 text-muted-foreground">
              Device memory under a stated sampling method. Missing telemetry stays unavailable,
              never substituted with zero.
            </dd>
          </div>
        </dl>
      </section>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-slate-100 px-5 py-4">
        <p className="text-sm text-slate-600">
          Local experiments. Reviewed snapshots. Public explanations.
        </p>
        <Link className="inline-link" to="/reports">
          Explore demo reports <ArrowRight size={14} aria-hidden="true" />
        </Link>
      </div>
    </>
  );
}
