import { ArrowLeftRight, Info } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { PageHeading } from '@/components/PageHeading';
import { Card, CardContent } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
  TableCaption,
} from '@/components/ui/table';
import { useDemoData } from '@/api/hooks';

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
  return (
    <>
      <PageHeading
        eyebrow="SIDE-BY-SIDE EXPLORATION"
        title="Compare models"
        description="Put example configurations side by side. Context comes before conclusions."
      />
      <div className="mb-6 grid items-center gap-4 md:grid-cols-[1fr_auto_1fr]">
        {(['left', 'right'] as const)
          .map((side, index) => (
            <Card key={side} className="shadow-none">
              <CardContent className="p-5">
                <label className="block">
                  <span className="mb-3 block text-xs font-medium text-muted-foreground">
                    {index === 0 ? 'CONFIGURATION A' : 'CONFIGURATION B'}
                  </span>
                  <select
                    className="native-select w-full"
                    aria-label={`Configuration ${index === 0 ? 'A' : 'B'}`}
                    value={side === 'left' ? left.id : right.id}
                    onChange={(e) => choose(side, e.target.value)}
                  >
                    {demoModels.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.name} · {model.size}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="mt-3 font-mono text-xs text-muted-foreground">
                  Ollama / Q4_K_M / demo-only revision
                </p>
              </CardContent>
            </Card>
          ))
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
      <div className="mb-6 flex gap-3 rounded-lg border border-amber-200 bg-amber-50 p-4 text-xs leading-5 text-amber-900">
        <Info size={17} className="shrink-0" aria-hidden="true" />
        <p>
          {left.id === right.id
            ? 'The same demo model is selected on both sides.'
            : 'Different model revisions and architectures are not a controlled baseline.'}{' '}
          These synthetic values demonstrate the interface; they cannot establish a speedup or
          quality advantage.
        </p>
      </div>
      <section className="rounded-xl border bg-white">
        <div className="panel-header">
          <div>
            <h2 className="section-title">Example metrics</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              DEMO DATA · missing metrics remain unavailable
            </p>
          </div>
        </div>
        <div
          className="table-scroll"
          role="region"
          aria-label="Model comparison table"
          tabIndex={0}
        >
          <Table>
            <TableCaption className="sr-only">
              Synthetic model comparison. All values are demo data.
            </TableCaption>
            <TableHeader>
              <TableRow>
                <TableHead>Metric</TableHead>
                <TableHead>
                  {left.name} · {left.size}
                </TableHead>
                <TableHead>
                  {right.name} · {right.size}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {[
                [
                  'Decode throughput',
                  left.throughput === null ? 'Unavailable' : `${left.throughput} tok/s`,
                  right.throughput === null ? 'Unavailable' : `${right.throughput} tok/s`,
                ],
                [
                  'Time to first token',
                  left.ttft === null ? 'Unavailable' : `${left.ttft} ms`,
                  right.ttft === null ? 'Unavailable' : `${right.ttft} ms`,
                ],
                [
                  'Illustrative VRAM',
                  left.memory === null ? 'Unavailable' : `${left.memory} MiB`,
                  right.memory === null ? 'Unavailable' : `${right.memory} MiB`,
                ],
                ['Quantization', left.quantization, right.quantization],
                ['Quality evaluation', 'Unavailable', 'Unavailable'],
                ['Measured sample size', 'Not measured', 'Not measured'],
              ].map(([label, a, b]) => (
                <TableRow key={label}>
                  <TableCell className="font-medium">{label}</TableCell>
                  <TableCell className="font-mono text-xs">{a}</TableCell>
                  <TableCell className="font-mono text-xs">{b}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>
      <p className="mt-4 text-xs leading-6 text-muted-foreground">
        Example settings: warm inference · 2K context · 256-token output budget · concurrency 1.
        Model checksums and actual runs will be required before publishing measurements.
      </p>
    </>
  );
}
