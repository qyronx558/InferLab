import { CircleCheck, CircleDashed, CircleX, Clock3 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { ExperimentStatus } from '@/data/demo';

const variants = {
  Completed: { icon: CircleCheck, className: 'border-emerald-200 bg-emerald-50 text-emerald-800' },
  Running: { icon: CircleDashed, className: 'border-blue-200 bg-blue-50 text-blue-800' },
  Queued: { icon: Clock3, className: 'border-slate-200 bg-slate-100 text-slate-700' },
  Failed: { icon: CircleX, className: 'border-red-200 bg-red-50 text-red-800' },
};
export function StatusBadge({ status }: { status: ExperimentStatus }) {
  const { icon: Icon, className } = variants[status];
  return (
    <Badge variant="outline" className={`gap-1.5 whitespace-nowrap font-medium ${className}`}>
      <Icon size={12} aria-hidden="true" />
      {status}
    </Badge>
  );
}
