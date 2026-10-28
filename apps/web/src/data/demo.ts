// Presentation-only adaptation of generated, Pydantic-validated wire fixtures.
// Percentiles and summary metrics come from the fixture. Aggregate output
// throughput is derived transparently from accepted run tokens and latencies.
import type {
  ContractCatalog,
  ExecutionState,
  Experiment,
  ExperimentConfig,
  Provenance,
  RunMetrics,
  Summary,
} from '@/api/types';

export type ExperimentStatus = ExecutionState;
export type DataLabel = 'DEMO DATA' | 'MEASURED DATA' | 'MIXED DATA';

export type ComparisonMeasurement = {
  value: number | null;
  unit: string;
  unavailableReason: string | null;
};

export type ComparisonMeasurements = {
  decodeThroughput: ComparisonMeasurement;
  ttft: ComparisonMeasurement;
  p95Latency: ComparisonMeasurement;
  aggregateThroughput: ComparisonMeasurement;
  peakVram: ComparisonMeasurement;
  quality: ComparisonMeasurement;
};

export type ComparisonModel = {
  id: string;
  experimentId: string | null;
  name: string;
  size: string;
  revision: string;
  quantization: string;
  promptId: string | null;
  workloadId: string | null;
  promptDistribution: string;
  sampleCount: number;
  acceptedRunIds: string[];
  errorCount: number;
  condition: ExperimentConfig['condition'] | null;
  contextTokens: number | null;
  inputTokenBudget: number | null;
  maxOutputTokens: number | null;
  concurrency: number | null;
  sampling: ExperimentConfig['sampling'] | null;
  hardware: {
    deviceName: string | null;
    deviceMemoryMib: number | null;
    driverVersion: string | null;
    gpuDeviceId: string | null;
    gpuLayers: number | null;
    settings: string | null;
  };
  hardwareLabel: string;
  dataLabel: DataLabel;
  measurements: ComparisonMeasurements;
  runs: RunMetrics[];
  config: ExperimentConfig | null;
  provenance: Provenance | null;
  summary: Summary | null;
  color: string;
};

function fromSummaryMetric(metric: {
  value: number | null;
  unit: string;
  unavailable_reason: string | null;
}): ComparisonMeasurement {
  return {
    value: metric.value,
    unit: metric.unit,
    unavailableReason: metric.unavailable_reason,
  };
}

function unavailable(unit: string, reason = 'no_samples'): ComparisonMeasurement {
  return { value: null, unit, unavailableReason: reason };
}

function acceptedRuns(experiment: Experiment | undefined, runs: RunMetrics[]) {
  if (!experiment) return [];
  const accepted = new Set(experiment.summary.accepted_run_ids);
  return runs.filter(
    (run) => accepted.has(run.id) && run.state === 'complete' && run.kind === 'measured',
  );
}

function aggregateOutputThroughput(runs: RunMetrics[]): ComparisonMeasurement {
  if (!runs.length) return unavailable('tok/s', 'not_measured');
  if (runs.some((run) => run.output_tokens === null || run.request_latency.value === null)) {
    return unavailable('tok/s', 'incomplete_run_data');
  }
  const totals = runs.reduce(
    (result, run) => ({
      tokens: result.tokens + (run.output_tokens ?? 0),
      seconds: result.seconds + (run.request_latency.value ?? 0) / 1000,
    }),
    { tokens: 0, seconds: 0 },
  );
  if (totals.seconds <= 0) return unavailable('tok/s', 'not_measured');
  return {
    value: totals.tokens / totals.seconds,
    unit: 'tok/s',
    unavailableReason: null,
  };
}

function inputTokenRange(runs: RunMetrics[]) {
  const values = runs
    .map((run) => run.input_tokens)
    .filter((value): value is number => value !== null);
  if (!values.length) return 'input token counts unavailable';
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  return minimum === maximum
    ? `${minimum} input tokens/sample`
    : `${minimum}–${maximum} input tokens/sample`;
}

export function toDashboardView(
  source: Pick<ContractCatalog, 'registry' | 'experiments' | 'runs' | 'reports'>,
) {
  if (
    source.registry.state !== 'complete' ||
    source.experiments.state !== 'complete' ||
    source.runs.state !== 'complete' ||
    source.reports.state !== 'complete'
  ) {
    throw new Error('Cannot present unavailable resources as successful results');
  }
  const experiments = source.experiments.data.items;
  const runs = source.runs.data;
  const dataLabel = source.experiments.label;
  const colors = ['#3563c9', '#6382bb', '#94a8cb'];
  const demoModels: ComparisonModel[] = source.registry.data.models.map((model, index) => {
    const experiment = experiments.find(
      (item) => item.config.model_id === model.id && item.summary.state === 'complete',
    );
    const summary = experiment?.summary ?? null;
    const measuredRuns = acceptedRuns(experiment, runs);
    const hardware = experiment?.provenance.hardware;
    const workload = experiment?.provenance.workload;
    const config = experiment?.config ?? null;
    const promptId = config?.prompt_id ?? workload?.prompt_id ?? null;
    const workloadId = config?.workload_id ?? workload?.id ?? null;
    const hardwareLabel = hardware
      ? `${hardware.device_name} · ${hardware.device_memory_mib} MiB · driver ${hardware.driver_version}`
      : 'Hardware context unavailable';
    return {
      id: model.id,
      experimentId: experiment?.id ?? null,
      name: model.name,
      size: model.parameter_size,
      revision: config?.model_revision ?? model.revision,
      quantization: config?.quantization ?? model.quantization,
      promptId,
      workloadId,
      promptDistribution: `${promptId ?? 'prompt unavailable'} · ${inputTokenRange(measuredRuns)}`,
      sampleCount: summary?.sample_count ?? 0,
      acceptedRunIds: summary?.accepted_run_ids ?? [],
      errorCount: summary?.error_count ?? 0,
      condition: config?.condition ?? null,
      contextTokens: config?.context_tokens ?? null,
      inputTokenBudget: config?.input_token_budget ?? null,
      maxOutputTokens: config?.max_output_tokens ?? null,
      concurrency: config?.concurrency ?? null,
      sampling: config?.sampling ?? null,
      hardware: {
        deviceName: hardware?.device_name ?? null,
        deviceMemoryMib: hardware?.device_memory_mib ?? null,
        driverVersion: hardware?.driver_version ?? null,
        gpuDeviceId: hardware?.gpu_device_id ?? null,
        gpuLayers: hardware?.gpu_layers ?? null,
        settings: hardware?.gpu_settings ?? null,
      },
      hardwareLabel,
      dataLabel,
      measurements: {
        decodeThroughput: summary
          ? fromSummaryMetric(summary.decode_throughput)
          : unavailable('tok/s'),
        ttft: summary ? fromSummaryMetric(summary.ttft_median) : unavailable('ms'),
        p95Latency: summary ? fromSummaryMetric(summary.request_latency_p95) : unavailable('ms'),
        aggregateThroughput: aggregateOutputThroughput(measuredRuns),
        peakVram: summary ? fromSummaryMetric(summary.peak_vram) : unavailable('MiB'),
        quality: summary ? fromSummaryMetric(summary.quality) : unavailable('score'),
      },
      runs: measuredRuns,
      config,
      provenance: experiment?.provenance ?? null,
      summary,
      color: colors[index] ?? colors[0] ?? '#3563c9',
    };
  });
  const demoExperiments = experiments.map((item) => ({
    id: item.id,
    name: item.name,
    model: `${item.provenance.model.name} ? ${item.provenance.model.parameter_size}`,
    engine: item.provenance.engine.name,
    status: item.job.state,
    tokensPerSecond: item.summary.decode_throughput.value,
    date: new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      timeZone: 'UTC',
    }).format(new Date(item.job.created_at)),
  }));
  const demoReports = source.reports.data.map((report) => ({
    id: report.id,
    title: report.title,
    description: report.description,
    category: report.category,
    date: new Intl.DateTimeFormat('en-US', {
      month: 'long',
      day: 'numeric',
      year: 'numeric',
      timeZone: 'UTC',
    }).format(new Date(report.published_at)),
    experiments: report.summary.experiment_id,
    wire: report,
  }));
  return { demoModels, demoExperiments, demoReports };
}
export type ExperimentRow = ReturnType<typeof toDashboardView>['demoExperiments'][number];
