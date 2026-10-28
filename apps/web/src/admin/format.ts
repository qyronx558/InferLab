import type { Job } from '@/api/types';

const dateFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: 'medium',
  timeStyle: 'short',
});

export function formatDateTime(value: string | null | undefined) {
  if (!value) return 'Not recorded';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return dateFormatter.format(date);
}

export function formatNumber(value: number | null | undefined, digits = 2) {
  if (value === null || value === undefined) return 'Not set';
  return value.toFixed(digits).replace(/\.?0+$/, '');
}

export const jobErrorMessages: Record<NonNullable<Job['error_code']>, string> = {
  validation_error: 'The config or evidence failed validation.',
  worker_lost: 'The worker stopped renewing its lease. Recovery will reconcile the attempt.',
  engine_unavailable: 'The inference engine was unavailable.',
  out_of_memory: 'The run exceeded available memory.',
  timeout: 'The run exceeded its configured timeout.',
  cancelled: 'The job was cancelled.',
};
