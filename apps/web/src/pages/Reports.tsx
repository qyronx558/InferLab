import { FileChartColumn, ArrowDownToLine } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { PageHeading } from '@/components/PageHeading';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { EmptyState } from '@/components/EmptyState';
import { useDemoData } from '@/api/hooks';

export function Reports() {
  const { demoReports, dataLabel } = useDemoData();
  const [params, setParams] = useSearchParams();
  const experiment = params.get('experiment');
  const reports = demoReports.filter(
    (report) => !experiment || report.experiments.split(', ').includes(experiment),
  );
  const fileStem =
    dataLabel === 'DEMO DATA' ? 'demo' : dataLabel === 'MIXED DATA' ? 'mixed' : 'measured';
  const download = () => {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              label: dataLabel,
              synthetic: dataLabel !== 'MEASURED DATA',
              reports: reports.map((report) => report.wire),
            },
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
    anchor.download = `inferlab-${fileStem}-reports.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <>
      <PageHeading
        eyebrow="PUBLISHED KNOWLEDGE"
        title="Reports & findings"
        description={
          dataLabel === 'DEMO DATA'
            ? 'An example library of reviewed experiment narratives. These are synthetic previews, not published scientific findings.'
            : 'Reviewed reports from this published static snapshot, with accepted run evidence and stated limitations.'
        }
        action={
          <Button variant="outline" onClick={download}>
            <ArrowDownToLine size={15} aria-hidden="true" />
            Export {fileStem} JSON
          </Button>
        }
      />
      {experiment && (
        <div className="mb-5 flex items-center gap-4 text-sm">
          <p>
            {dataLabel === 'DEMO DATA' ? 'Demo' : 'Snapshot'} context:{' '}
            <span className="font-mono">{experiment}</span>
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
                      <span className="subtle-tag">{report.label}</span>
                      <span className="text-xs text-muted-foreground">{report.category}</span>
                    </div>
                    <h2 className="text-lg font-semibold tracking-tight">{report.title}</h2>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {report.description}
                    </p>
                    <p className="mt-3 font-mono text-[11px] text-muted-foreground">
                      {report.id} · {report.label === 'DEMO DATA' ? 'Example' : 'Published'} date:{' '}
                      {report.date}
                    </p>
                    <details className="report-detail">
                      <summary>
                        Read {report.label === 'DEMO DATA' ? 'demo' : 'published'} report
                      </summary>
                      <div className="mt-4 space-y-3 text-sm leading-6 text-muted-foreground">
                        <p>
                          {report.label === 'DEMO DATA'
                            ? 'This narrative is a UI fixture. It contains no measured findings. The final report will explain conditions, error counts and limitations before drawing conclusions.'
                            : 'This reviewed snapshot explains the recorded conditions, accepted runs, unavailable measurements and limitations before drawing conclusions.'}
                        </p>
                        <dl>
                          <dt className="font-medium text-foreground">
                            {report.label === 'DEMO DATA' ? 'Illustrative' : 'Published'} source
                            experiments
                          </dt>
                          <dd className="font-mono text-xs">{report.experiments}</dd>
                          <dt className="mt-3 font-medium text-foreground">
                            Reproducibility status
                          </dt>
                          <dd>
                            {report.label === 'DEMO DATA'
                              ? 'Pending real model checksums, engine build, workload hash and measured runs.'
                              : 'Pinned model revision, checksum, engine build, workload hash and accepted measured runs are included in the snapshot.'}
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
          title={
            experiment
              ? dataLabel === 'DEMO DATA'
                ? 'No report for this demo run'
                : 'No report for this published run'
              : 'No published reports yet'
          }
          description={
            experiment
              ? 'Queued, running and failed examples do not have completed reports.'
              : 'This release contains no reviewed report snapshots.'
          }
          onReset={() => setParams({})}
        />
      )}
    </>
  );
}
