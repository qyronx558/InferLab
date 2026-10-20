import { CircleCheck, CircleDashed, CircleX, Clock3, CircleSlash, WifiOff } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import type { ExperimentStatus } from '@/data/demo';

const variants = {
  complete: {
    label: 'Completed',
    icon: CircleCheck,
    className: 'border-emerald-200 bg-emerald-50 text-emerald-800',
  },
  running: {
    label: 'Running',
    icon: CircleDashed,
    className: 'border-blue-200 bg-blue-50 text-blue-800',
  },
  pending: {
    label: 'Pending',
    icon: Clock3,
    className: 'border-slate-200 bg-slate-100 text-slate-700',
  },
  failed: { label: 'Failed', icon: CircleX, className: 'border-red-200 bg-red-50 text-red-800' },
  cancelled: {
    label: 'Cancelled',
    icon: CircleSlash,
    className: 'border-slate-200 bg-slate-100 text-slate-700',
  },
  unavailable: {
    label: 'Unavailable',
    icon: WifiOff,
    className: 'border-amber-200 bg-amber-50 text-amber-900',
  },
};
export function StatusBadge({ status }: { status: ExperimentStatus }) {
  const { icon: Icon, className, label } = variants[status];
  return (
    <Badge variant="outline" className={`gap-1.5 whitespace-nowrap font-medium ${className}`}>
      <Icon size={12} aria-hidden="true" />
      {label}
    </Badge>
  );
}
