import type { ComparisonMeasurement, ComparisonModel, DataLabel } from './demo';

export type ComparisonMetricKey = keyof ComparisonModel['measurements'];

export type ComparisonMetric = {
  key: ComparisonMetricKey;
  label: string;
  shortLabel: string;
  unit: string;
  higherIsBetter: boolean;
  description: string;
  format: (value: number) => string;
};

export const comparisonMetrics: ComparisonMetric[] = [
  {
    key: 'decodeThroughput',
    label: 'Decode throughput',
    shortLabel: 'Decode TPS',
    unit: 'tok/s',
    higherIsBetter: true,
    description: 'Summary decode tokens per second from accepted measured samples.',
    format: (value) => value.toFixed(1),
  },
  {
    key: 'ttft',
    label: 'Time to first token',
    shortLabel: 'TTFT',
    unit: 'ms',
    higherIsBetter: false,
    description: 'Median time to first token reported by the fixture summary.',
    format: (value) => Math.round(value).toLocaleString('en-US'),
  },
  {
    key: 'p95Latency',
    label: 'Request latency p95',
    shortLabel: 'p95 latency',
    unit: 'ms',
    higherIsBetter: false,
    description: '95th percentile request latency reported by the fixture summary.',
    format: (value) => Math.round(value).toLocaleString('en-US'),
  },
  {
    key: 'aggregateThroughput',
    label: 'Aggregate throughput',
    shortLabel: 'Aggregate TPS',
    unit: 'tok/s',
    higherIsBetter: true,
    description:
      'Derived as accepted output tokens divided by summed request latency; not a summary field.',
    format: (value) => value.toFixed(1),
  },
  {
    key: 'peakVram',
    label: 'Peak VRAM',
    shortLabel: 'Peak VRAM',
    unit: 'MiB',
    higherIsBetter: false,
    description: 'Peak device memory reported for accepted measured samples.',
    format: (value) => Math.round(value).toLocaleString('en-US'),
  },
  {
    key: 'quality',
    label: 'Quality score',
    shortLabel: 'Quality',
    unit: 'score',
    higherIsBetter: true,
    description: 'Fixture quality score on a 0–1 scale; unavailable when not measured.',
    format: (value) => value.toFixed(2),
  },
];

const contextFields: {
  label: string;
  value: (side: ComparisonModel) => string;
}[] = [
  { label: 'Model', value: (side) => `${side.name} (${side.id})` },
  { label: 'Model revision', value: (side) => side.revision },
  { label: 'Quantization', value: (side) => side.quantization },
  { label: 'Prompt / workload', value: (side) => side.promptDistribution },
  { label: 'Sample count', value: (side) => String(side.sampleCount) },
  { label: 'Engine', value: (side) => side.provenance?.engine.name ?? 'Unavailable' },
  { label: 'Engine build', value: (side) => side.provenance?.engine.build ?? 'Unavailable' },
  { label: 'Hardware', value: (side) => side.hardwareLabel },
  { label: 'GPU settings', value: (side) => side.hardware.settings ?? 'Unavailable' },
  {
    label: 'Condition',
    value: (side) => side.condition ?? 'Unavailable',
  },
  {
    label: 'Context window',
    value: (side) => (side.contextTokens === null ? 'Unavailable' : `${side.contextTokens} tokens`),
  },
  {
    label: 'Input budget',
    value: (side) =>
      side.inputTokenBudget === null ? 'Unavailable' : `${side.inputTokenBudget} tokens`,
  },
  {
    label: 'Output budget',
    value: (side) =>
      side.maxOutputTokens === null ? 'Unavailable' : `${side.maxOutputTokens} tokens`,
  },
  {
    label: 'Sampling',
    value: (side) =>
      side.sampling
        ? `temperature ${side.sampling.temperature} · top-p ${side.sampling.top_p} · seed ${
            side.sampling.seed ?? 'none'
          }`
        : 'Unavailable',
  },
  {
    label: 'Concurrency',
    value: (side) => (side.concurrency === null ? 'Unavailable' : String(side.concurrency)),
  },
];

export function comparisonDataLabel(left: ComparisonModel, right: ComparisonModel): DataLabel {
  return left.dataLabel === right.dataLabel ? left.dataLabel : 'MIXED DATA';
}

export function differingContextFields(left: ComparisonModel, right: ComparisonModel) {
  return contextFields
    .filter((field) => field.value(left) !== field.value(right))
    .map((field) => field.label);
}

export function comparisonContextRows(left: ComparisonModel, right: ComparisonModel) {
  return contextFields.map((field) => ({
    label: field.label,
    left: field.value(left),
    right: field.value(right),
  }));
}

export function comparisonNotice(left: ComparisonModel, right: ComparisonModel) {
  if (left.id === right.id) {
    return {
      title: 'Same demo model selected on both sides',
      body: 'The values repeat the same demo experiment. This is not an independent comparison and does not establish a speedup or quality advantage.',
      differences: [] as string[],
    };
  }
  const differences = differingContextFields(left, right);
  return {
    title: 'Observational comparison, not a controlled experiment',
    body: `The configurations differ in ${differences.join(
      ', ',
    )}. These views report fixture values only; they do not establish that any difference is caused by the model.`,
    differences,
  };
}

export function formatMeasurement(metric: ComparisonMetric, measurement: ComparisonMeasurement) {
  if (measurement.value === null) {
    const reason = measurement.unavailableReason?.replaceAll('_', ' ') ?? 'unavailable';
    return `Unavailable (${reason})`;
  }
  return `${metric.format(measurement.value)} ${metric.unit}`;
}

export function measurementFor(side: ComparisonModel, key: ComparisonMetricKey) {
  return side.measurements[key];
}

export function buildComparisonExport(
  left: ComparisonModel,
  right: ComparisonModel,
  generatedAt = new Date().toISOString(),
) {
  const label = comparisonDataLabel(left, right);
  const notice = comparisonNotice(left, right);
  return {
    schema_version: '1.0',
    label,
    synthetic: left.dataLabel !== 'MEASURED DATA' || right.dataLabel !== 'MEASURED DATA',
    data_labels: [left.dataLabel, right.dataLabel],
    generated_at: generatedAt,
    observational: true,
    causal_claim: false,
    differing_context_fields: notice.differences,
    warning: notice.body,
    sides: [left, right].map((side, index) => ({
      side: index === 0 ? 'A' : 'B',
      experiment_id: side.experimentId,
      model: {
        id: side.id,
        name: side.name,
        parameter_size: side.size,
        revision: side.revision,
        quantization: side.quantization,
        sha256: side.config?.model_sha256 ?? null,
      },
      prompt: {
        workload_id: side.workloadId,
        prompt_id: side.promptId,
        distribution: side.promptDistribution,
        sample_count: side.sampleCount,
        accepted_run_ids: side.acceptedRunIds,
        error_count: side.errorCount,
      },
      hardware: side.hardware,
      config: side.config,
      provenance: side.provenance,
      measurements: Object.fromEntries(
        comparisonMetrics.map((metric) => {
          const measurement = measurementFor(side, metric.key);
          return [
            metric.key,
            {
              label: metric.label,
              unit: metric.unit,
              value: measurement.value,
              unavailable_reason: measurement.unavailableReason,
            },
          ];
        }),
      ),
      runs: side.runs.map((run) => ({
        id: run.id,
        attempt: run.attempt,
        repetition: run.repetition,
        input_tokens: run.input_tokens,
        output_tokens: run.output_tokens,
        ttft_ms: run.ttft.value,
        request_latency_ms: run.request_latency.value,
        decode_tps: run.decode_throughput.value,
        peak_vram_mib: run.peak_vram.value,
        quality_score: run.quality.value,
      })),
    })),
  };
}

function csvCell(value: string | number | null) {
  const text = value === null ? '' : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

export function buildComparisonCsv(left: ComparisonModel, right: ComparisonModel) {
  const headers = [
    'side',
    'experiment_id',
    'model',
    'parameter_size',
    'model_revision',
    'quantization',
    'workload_id',
    'prompt_id',
    'prompt_distribution',
    'sample_count',
    'accepted_run_ids',
    'error_count',
    'hardware',
    'driver',
    'gpu_device_id',
    'condition',
    'context_tokens',
    'input_token_budget',
    'max_output_tokens',
    'concurrency',
    'decode_tps',
    'ttft_ms',
    'p95_latency_ms',
    'aggregate_throughput_tps',
    'peak_vram_mib',
    'quality_score',
    'data_label',
  ];
  const rows = [left, right].map((side, index) => {
    const values: (string | number | null)[] = [
      index === 0 ? 'A' : 'B',
      side.experimentId,
      side.name,
      side.size,
      side.revision,
      side.quantization,
      side.workloadId,
      side.promptId,
      side.promptDistribution,
      side.sampleCount,
      side.acceptedRunIds.join(' '),
      side.errorCount,
      side.hardwareLabel,
      side.hardware.driverVersion,
      side.hardware.gpuDeviceId,
      side.condition,
      side.contextTokens,
      side.inputTokenBudget,
      side.maxOutputTokens,
      side.concurrency,
      ...comparisonMetrics.map((metric) => measurementFor(side, metric.key).value),
      side.dataLabel,
    ];
    return values.map(csvCell).join(',');
  });
  return [headers.join(','), ...rows].join('\r\n');
}
