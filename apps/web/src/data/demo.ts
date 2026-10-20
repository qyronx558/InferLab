// Presentation-only adaptation of generated, Pydantic-validated wire fixtures.
// No timings, percentiles, throughput or quality scores are calculated here.
import type { ContractCatalog, ExecutionState } from '@/api/types';

export type ExperimentStatus = ExecutionState;
export function toDashboardView(
  source: Pick<ContractCatalog, 'registry' | 'experiments' | 'reports'>,
) {
  if (
    source.registry.state !== 'complete' ||
    source.experiments.state !== 'complete' ||
    source.reports.state !== 'complete'
  ) {
    throw new Error('Cannot present unavailable resources as successful results');
  }
  const experiments = source.experiments.data.items;
  const colors = ['#3563c9', '#6382bb', '#94a8cb'];
  const demoModels = source.registry.data.models.map((model, index) => {
    const summary = experiments.find(
      (item) => item.config.model_id === model.id && item.summary.state === 'complete',
    )?.summary;
    return {
      id: model.id,
      name: model.name,
      size: model.parameter_size,
      quantization: model.quantization,
      throughput: summary?.decode_throughput.value ?? null,
      ttft: summary?.ttft_median.value ?? null,
      memory: summary?.peak_vram.value ?? null,
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
