import { ArrowDownToLine, ArrowLeft, Printer } from 'lucide-react';
import { useMemo } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { PageHeading } from '@/components/PageHeading';
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
import { useDemoData } from '@/api/hooks';
import { ComparisonChart } from '@/components/comparison/ComparisonChart';
import { ComparisonContext } from '@/components/comparison/ComparisonContext';
import { ComparisonMetricTable } from '@/components/comparison/ComparisonMetricTable';
import { ComparisonNotice } from '@/components/comparison/ComparisonNotice';
import {
  buildComparisonCsv,
  buildComparisonExport,
  comparisonDataLabel,
  comparisonMetrics,
} from '@/data/comparison';
import type { ComparisonModel } from '@/data/demo';
import { downloadText } from '@/lib/download';

function formatNullable(value: number | null, unit: string) {
  return value === null ? 'Unavailable' : `${value.toLocaleString('en-US')} ${unit}`;
}

function RunEvidence({ side, label }: { side: ComparisonModel; label: string }) {
  return (
    <>
      {side.runs.length === 0 ? (
        <TableRow>
          <TableCell className="font-medium">{label}</TableCell>
          <TableCell colSpan={11} className="text-muted-foreground">
            No accepted measured runs.
          </TableCell>
        </TableRow>
      ) : (
        side.runs.map((run) => (
          <TableRow key={run.id}>
            <TableCell className="font-medium">{label}</TableCell>
            <TableCell className="font-mono text-xs">{run.id}</TableCell>
            <TableCell>{run.attempt}</TableCell>
            <TableCell>{run.repetition}</TableCell>
            <TableCell>{run.input_tokens ?? 'Unavailable'}</TableCell>
            <TableCell>{run.output_tokens ?? 'Unavailable'}</TableCell>
            <TableCell>{formatNullable(run.ttft.value, 'ms')}</TableCell>
            <TableCell>{formatNullable(run.request_latency.value, 'ms')}</TableCell>
            <TableCell>{formatNullable(run.decode_throughput.value, 'tok/s')}</TableCell>
            <TableCell>{formatNullable(run.peak_vram.value, 'MiB')}</TableCell>
            <TableCell>
              {run.quality.value === null ? 'Unavailable' : run.quality.value.toFixed(2)}
            </TableCell>
          </TableRow>
        ))
      )}
    </>
  );
}

export function CompareReport() {
  const { demoModels, snapshot } = useDemoData();
  const [params] = useSearchParams();
  const generatedAt = useMemo(() => new Date().toISOString(), []);
  const left = demoModels.find((model) => model.id === params.get('left')) ?? demoModels[0];
  const right = demoModels.find((model) => model.id === params.get('right')) ?? demoModels[1];
  if (!left || !right)
    return (
      <p role="status">
        Two {snapshot.status === 'snapshot' ? 'published' : 'demo'} model configurations are
        required to compare.
      </p>
    );

  const dataLabel = comparisonDataLabel(left, right);
  const fileStem =
    dataLabel === 'DEMO DATA' ? 'demo' : dataLabel === 'MIXED DATA' ? 'mixed' : 'measured';
  const compareHref = `/compare?${new URLSearchParams({
    left: left.id,
    right: right.id,
  }).toString()}`;
  const exportJson = () => {
    downloadText(
      `inferlab-compare-${fileStem}.json`,
      'application/json',
      JSON.stringify(buildComparisonExport(left, right, generatedAt), null, 2),
    );
  };
  const exportCsv = () => {
    downloadText(
      `inferlab-compare-${fileStem}.csv`,
      'text/csv;charset=utf-8',
      buildComparisonCsv(left, right),
    );
  };

  return (
    <div className="print-report">
      <PageHeading
        eyebrow="PRINTABLE COMPARISON REPORT"
        title="Comparison report"
        description={`A print-ready record of the selected ${
          snapshot.status === 'snapshot' ? 'published' : 'fixture'
        } runs, including model, prompt, sample and hardware context. This is an observational comparison, not a controlled experiment.`}
        action={
          <div className="print-controls flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => window.print()}>
              <Printer size={15} aria-hidden="true" />
              Print
            </Button>
            <Button variant="outline" size="sm" onClick={exportCsv}>
              <ArrowDownToLine size={15} aria-hidden="true" />
              CSV
            </Button>
            <Button variant="outline" size="sm" onClick={exportJson}>
              <ArrowDownToLine size={15} aria-hidden="true" />
              JSON
            </Button>
            <Button variant="ghost" size="sm" asChild>
              <Link to={compareHref}>
                <ArrowLeft size={15} aria-hidden="true" />
                Back to comparison
              </Link>
            </Button>
          </div>
        }
      />
      <section className="report-meta" aria-label="Report metadata">
        <span className="subtle-tag">{dataLabel}</span>
        <dl>
          <div>
            <dt>Generated</dt>
            <dd>{generatedAt}</dd>
          </div>
          {snapshot.publishedAt && (
            <div>
              <dt>Snapshot</dt>
              <dd>
                {snapshot.publishedAt} · {snapshot.releaseId}
              </dd>
            </div>
          )}
          <div>
            <dt>Configuration A</dt>
            <dd>
              {left.name} · {left.experimentId ?? 'No experiment'}
            </dd>
          </div>
          <div>
            <dt>Configuration B</dt>
            <dd>
              {right.name} · {right.experimentId ?? 'No experiment'}
            </dd>
          </div>
        </dl>
      </section>
      <ComparisonNotice left={left} right={right} />
      <ComparisonContext left={left} right={right} dataLabel={dataLabel} />
      <section className="comparison-chart-section" aria-labelledby="report-charts-heading">
        <div className="comparison-chart-section-heading">
          <div>
            <h2 id="report-charts-heading" className="section-title">
              Metric views
            </h2>
            <p>
              Six requested views with the same context beside each chart. Missing values remain
              unavailable and are not plotted as zero.
            </p>
          </div>
          <span className="subtle-tag">{dataLabel}</span>
        </div>
        <div className="comparison-chart-grid">
          {comparisonMetrics.map((metric) => (
            <ComparisonChart
              key={metric.key}
              metric={metric}
              left={left}
              right={right}
              dataLabel={dataLabel}
            />
          ))}
        </div>
      </section>
      <ComparisonMetricTable left={left} right={right} dataLabel={dataLabel} />
      <section className="comparison-context-panel" aria-labelledby="run-evidence-heading">
        <div className="panel-header">
          <div>
            <h2 id="run-evidence-heading" className="section-title">
              Accepted run evidence
            </h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Only accepted measured runs are listed. Warmups, failed runs and cancelled runs are
              excluded from the summary views above.
            </p>
          </div>
          <span className="subtle-tag">{dataLabel}</span>
        </div>
        <div
          className="table-scroll"
          role="region"
          aria-label="Accepted measured run evidence"
          tabIndex={0}
        >
          <Table>
            <TableCaption className="sr-only">
              Accepted measured run identifiers and recorded values for both configurations.
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Side</TableHead>
                <TableHead>Run</TableHead>
                <TableHead>Attempt</TableHead>
                <TableHead>Repetition</TableHead>
                <TableHead>Input</TableHead>
                <TableHead>Output</TableHead>
                <TableHead>TTFT</TableHead>
                <TableHead>Latency</TableHead>
                <TableHead>Decode</TableHead>
                <TableHead>Peak VRAM</TableHead>
                <TableHead>Quality</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <RunEvidence side={left} label="A" />
              <RunEvidence side={right} label="B" />
            </TableBody>
          </Table>
        </div>
      </section>
      <section className="report-limitations" aria-labelledby="report-limitations-heading">
        <h2 id="report-limitations-heading" className="section-title">
          Limitations and interpretation
        </h2>
        <ul>
          <li>
            {dataLabel === 'DEMO DATA'
              ? 'All values are synthetic demo fixtures. No model, engine or GPU is connected.'
              : 'Values are from a published static snapshot; confirm provenance and limitations before reuse.'}
          </li>
          <li>
            Aggregate throughput is derived from accepted output tokens and summed request latency.
            It is not a summary field and does not measure concurrent serving capacity.
          </li>
          <li>
            Missing TTFT, p95, VRAM or quality values remain unavailable. They are never replaced
            with zero.
          </li>
          <li>
            Model revision, quantization, prompt distribution, sample count and hardware context can
            differ between sides. This comparison is uncontrolled; it does not establish causation
            or a general model ranking.
          </li>
          <li>
            A single sample or a small sample count is not evidence of stable performance. Read the
            sample count and accepted run evidence before drawing conclusions.
          </li>
        </ul>
      </section>
    </div>
  );
}
