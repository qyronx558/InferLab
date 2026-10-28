import { ArrowDownToLine, ArrowLeftRight, Printer } from 'lucide-react';
import { Link, useSearchParams } from 'react-router-dom';
import { PageHeading } from '@/components/PageHeading';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
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
import { downloadText } from '@/lib/download';

export function Compare() {
  const { demoModels } = useDemoData();
  const [params, setParams] = useSearchParams();
  const left = demoModels.find((model) => model.id === params.get('left')) ?? demoModels[0];
  const right = demoModels.find((model) => model.id === params.get('right')) ?? demoModels[1];
  if (!left || !right)
    return <p role="status">Two demo model configurations are required to compare.</p>;

  const choose = (side: string, value: string) => {
    const next = new URLSearchParams(params);
    next.set(side, value);
    setParams(next);
  };
  const dataLabel = comparisonDataLabel(left, right);
  const reportHref = `/compare/report?${new URLSearchParams({
    left: left.id,
    right: right.id,
  }).toString()}`;
  const fileStem =
    dataLabel === 'DEMO DATA' ? 'demo' : dataLabel === 'MIXED DATA' ? 'mixed' : 'measured';
  const exportJson = () => {
    downloadText(
      `inferlab-compare-${fileStem}.json`,
      'application/json',
      JSON.stringify(buildComparisonExport(left, right), null, 2),
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
    <>
      <PageHeading
        eyebrow="OBSERVATIONAL COMPARISON"
        title="Compare models"
        description="Compare fixture values with revision, quantization, prompt distribution, sample count and hardware context attached to every chart."
        action={
          <div className="flex flex-wrap gap-2 print:hidden">
            <Button variant="outline" size="sm" onClick={exportCsv}>
              <ArrowDownToLine size={15} aria-hidden="true" />
              CSV
            </Button>
            <Button variant="outline" size="sm" onClick={exportJson}>
              <ArrowDownToLine size={15} aria-hidden="true" />
              JSON
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link to={reportHref}>
                <Printer size={15} aria-hidden="true" />
                Printable report
              </Link>
            </Button>
          </div>
        }
      />
      <div className="mb-6 grid items-center gap-4 md:grid-cols-[1fr_auto_1fr]">
        {(['left', 'right'] as const)
          .map((side, index) => {
            const selected = side === 'left' ? left : right;
            return (
              <Card key={side} className="shadow-none">
                <CardContent className="p-5">
                  <label className="block">
                    <span className="mb-3 block text-xs font-medium text-muted-foreground">
                      {index === 0 ? 'CONFIGURATION A' : 'CONFIGURATION B'}
                    </span>
                    <select
                      className="native-select w-full"
                      aria-label={`Configuration ${index === 0 ? 'A' : 'B'}`}
                      value={selected.id}
                      onChange={(event) => choose(side, event.target.value)}
                    >
                      {demoModels.map((model) => (
                        <option key={model.id} value={model.id}>
                          {model.name} · {model.size}
                        </option>
                      ))}
                    </select>
                  </label>
                  <dl className="comparison-selection-context">
                    <div>
                      <dt>Revision</dt>
                      <dd>{selected.revision}</dd>
                    </div>
                    <div>
                      <dt>Quantization</dt>
                      <dd>{selected.quantization}</dd>
                    </div>
                    <div>
                      <dt>Prompt distribution</dt>
                      <dd>{selected.promptDistribution}</dd>
                    </div>
                    <div>
                      <dt>Sample count</dt>
                      <dd>{selected.sampleCount}</dd>
                    </div>
                    <div>
                      <dt>Hardware</dt>
                      <dd>{selected.hardwareLabel}</dd>
                    </div>
                  </dl>
                </CardContent>
              </Card>
            );
          })
          .flatMap((card, index) =>
            index === 0
              ? [
                  card,
                  <ArrowLeftRight
                    key="versus"
                    className="mx-auto text-slate-400"
                    size={20}
                    aria-hidden="true"
                  />,
                ]
              : [card],
          )}
      </div>
      <ComparisonNotice left={left} right={right} />
      <ComparisonContext left={left} right={right} dataLabel={dataLabel} />
      <section className="comparison-chart-section" aria-labelledby="comparison-charts-heading">
        <div className="comparison-chart-section-heading">
          <div>
            <h2 id="comparison-charts-heading" className="section-title">
              Six views of the selected runs
            </h2>
            <p>
              Every chart repeats the same context strip. Aggregate throughput is derived from
              accepted run tokens and request latency, not copied from the summary.
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
      <p className="comparison-footer-note">
        Demo fixtures only. No model, engine or GPU is connected. These comparisons are
        observational, not controlled experiments, and do not establish causation.
      </p>
    </>
  );
}
