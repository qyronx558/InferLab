import type { LucideIcon } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';

export function MetricCard({
  label,
  value,
  unit,
  detail,
  icon: Icon,
}: {
  label: string;
  value: string;
  unit?: string;
  detail: string;
  icon: LucideIcon;
}) {
  return (
    <Card className="shadow-none">
      <CardContent className="p-5">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <Icon size={16} className="text-slate-500" aria-hidden="true" />
        </div>
        <p className="mt-3 flex items-baseline gap-1.5">
          <span className="font-mono text-3xl font-semibold tracking-tight">{value}</span>
          <span className="text-xs text-muted-foreground">{unit}</span>
        </p>
        <p className="mt-2 text-xs text-muted-foreground">{detail}</p>
      </CardContent>
    </Card>
  );
}
