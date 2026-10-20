import { ArrowUpRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import {
  Table,
  TableBody,
  TableCaption,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { StatusBadge } from './StatusBadge';
import { demoExperiments } from '@/data/demo';

export function ExperimentTable({ rows = demoExperiments }: { rows?: typeof demoExperiments }) {
  return (
    <div className="table-scroll" role="region" aria-label="Demo experiments table" tabIndex={0}>
      <Table>
        <TableCaption className="sr-only">
          DEMO DATA. Synthetic experiment statuses and throughput; not measured results.
        </TableCaption>
        <TableHeader>
          <TableRow>
            <TableHead className="w-[35%]">Experiment</TableHead>
            <TableHead>Model / engine</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Decode tok/s</TableHead>
            <TableHead className="text-right">Created</TableHead>
            <TableHead>
              <span className="sr-only">Details</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.id}>
              <TableCell>
                <p className="font-medium">{row.name}</p>
                <p className="mt-1 font-mono text-[11px] text-muted-foreground">{row.id}</p>
              </TableCell>
              <TableCell>
                <p>{row.model}</p>
                <p className="mt-1 text-xs text-muted-foreground">{row.engine} · Q4_K_M</p>
              </TableCell>
              <TableCell>
                <StatusBadge status={row.status} />
              </TableCell>
              <TableCell className="text-right font-mono">
                {row.tokensPerSecond?.toFixed(1) ?? '—'}
              </TableCell>
              <TableCell className="whitespace-nowrap text-right text-xs text-muted-foreground">
                {row.date}
              </TableCell>
              <TableCell>
                <Link
                  className="table-action"
                  to={`/reports?experiment=${row.id}`}
                  aria-label={`View demo context for ${row.id}`}
                >
                  <ArrowUpRight size={16} aria-hidden="true" />
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
