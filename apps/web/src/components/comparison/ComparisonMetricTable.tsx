import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import type { ComparisonModel, DataLabel } from '@/data/demo';
import { comparisonMetrics, formatMeasurement, measurementFor } from '@/data/comparison';

export function ComparisonMetricTable({
  left,
  right,
  dataLabel,
}: {
  left: ComparisonModel;
  right: ComparisonModel;
  dataLabel: DataLabel;
}) {
  return (
    <section className="comparison-context-panel" aria-labelledby="comparison-metrics-heading">
      <div className="panel-header">
        <div>
          <h2 id="comparison-metrics-heading" className="section-title">
            Metric summary
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Values are repeated from the fixture summary or derived from accepted run records. A
            missing value is never shown as zero.
          </p>
        </div>
        <span className="subtle-tag">{dataLabel}</span>
      </div>
      <div
        className="table-scroll"
        role="region"
        aria-label="Comparison metric values"
        tabIndex={0}
      >
        <Table>
          <TableCaption className="sr-only">
            Decode throughput, TTFT, p95 latency, aggregate throughput, peak VRAM and quality for
            both configurations.
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Metric</TableHead>
              <TableHead>A · {left.name}</TableHead>
              <TableHead>B · {right.name}</TableHead>
              <TableHead>Direction</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {comparisonMetrics.map((metric) => (
              <TableRow key={metric.key}>
                <TableCell className="font-medium">{metric.label}</TableCell>
                <TableCell className="font-mono text-xs">
                  {formatMeasurement(metric, measurementFor(left, metric.key))}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {formatMeasurement(metric, measurementFor(right, metric.key))}
                </TableCell>
                <TableCell className="text-xs text-muted-foreground">
                  {metric.higherIsBetter ? 'Higher value' : 'Lower value'}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
