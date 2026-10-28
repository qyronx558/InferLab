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
import { comparisonContextRows } from '@/data/comparison';

export function ComparisonContext({
  left,
  right,
  dataLabel,
}: {
  left: ComparisonModel;
  right: ComparisonModel;
  dataLabel: DataLabel;
}) {
  const rows = comparisonContextRows(left, right);
  return (
    <section className="comparison-context-panel" aria-labelledby="comparison-context-heading">
      <div className="panel-header">
        <div>
          <h2 id="comparison-context-heading" className="section-title">
            Comparison context
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Read these fields before comparing any value. Sample count is the number of accepted
            measured runs, not the number of prompts attempted.
          </p>
        </div>
        <span className="subtle-tag">{dataLabel}</span>
      </div>
      <div
        className="table-scroll"
        role="region"
        aria-label="Comparison model and hardware context"
        tabIndex={0}
      >
        <Table>
          <TableCaption className="sr-only">
            Model revision, quantization, prompt distribution, sample count and hardware context for
            both configurations.
          </TableCaption>
          <TableHeader>
            <TableRow>
              <TableHead>Context</TableHead>
              <TableHead>
                A · {left.name} ({left.size})
              </TableHead>
              <TableHead>
                B · {right.name} ({right.size})
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.label}>
                <TableCell className="font-medium">{row.label}</TableCell>
                <TableCell className="font-mono text-xs">{row.left}</TableCell>
                <TableCell className="font-mono text-xs">{row.right}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </section>
  );
}
