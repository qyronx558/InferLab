import { FileChartColumn, ArrowDownToLine } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { PageHeading } from '@/components/PageHeading';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/EmptyState';
import { useDemoData } from '@/api/hooks';

export function Reports() {
  const { demoReports } = useDemoData();
  const [params, setParams] = useSearchParams();
  const experiment = params.get('experiment');
  const reports = demoReports.filter(
    (report) => !experiment || report.experiments.split(', ').includes(experiment),
  );
  const download = () => {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            { label: 'DEMO DATA', synthetic: true, reports: reports.map((report) => report.wire) },
            null,
            2,
          ),
        ],
        {
          type: 'application/json',
        },
      ),
    );
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'inferlab-demo-reports.json';
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <PageHeading
        eyebrow="PUBLISHED KNOWLEDGE"
        title="Reports & findings"
        description="An example library of reviewed experiment narratives. These are synthetic previews, not published scientific findings."
        action={
          <Button variant="outline" onClick={download}>
            <ArrowDownToLine size={15} aria-hidden="true" />
            Export demo JSON
          </Button>
        }
      />
      {experiment && (
        <div className="mb-5 flex items-center gap-4 text-sm">
          <p>
            Demo context: <span className="font-mono">{experiment}</span>
          </p>
          <Button variant="ghost" size="sm" onClick={() => setParams({})}>
            Show all reports
          </Button>
        </div>
      )}
      {reports.length ? (
        <div className="grid gap-5">
          {reports.map((report) => (
            <Card key={report.id} className="shadow-none">
              <CardContent className="p-6">
                <div className="flex items-start gap-4">
                  <span className="hidden rounded-lg bg-blue-50 p-3 text-primary sm:block">
                    <FileChartColumn size={23} aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="mb-3 flex flex-wrap items-center gap-3">
                      <span className="subtle-tag">DEMO DATA</span>
                      <span className="text-xs text-muted-foreground">{report.category}</span>
                    </div>
                    <h2 className="text-lg font-semibold tracking-tight">{report.title}</h2>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {report.description}
                    </p>
                    <p className="mt-3 font-mono text-[11px] text-muted-foreground">
                      {report.id} · Example date: {report.date}
                    </p>
                    <details className="report-detail">
                      <summary>Read demo report</summary>
                      <div className="mt-4 space-y-3 text-sm leading-6 text-muted-foreground">
                        <p>
                          This narrative is a UI fixture. It contains no measured findings. The
                          final report will explain conditions, error counts and limitations before
                          drawing conclusions.
                        </p>
                        <dl>
                          <dt className="font-medium text-foreground">
                            Illustrative source experiments
                          </dt>
                          <dd className="font-mono text-xs">{report.experiments}</dd>
                          <dt className="mt-3 font-medium text-foreground">
                            Reproducibility status
                          </dt>
                          <dd>
                            Pending real model checksums, engine build, workload hash and measured
                            runs.
                          </dd>
                        </dl>
                      </div>
                    </details>
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState
          title="No report for this demo run"
          description="Queued, running and failed examples do not have completed reports."
          onReset={() => setParams({})}
        />
      )}
    </>
  );
}
