import { z } from 'zod';
import type { ContractCatalog, Experiment, Job, PublishedReport, RunMetrics } from './types';
import { engineSchema, experimentConfigSchema, modelSchema, workloadSchema } from './schemas';

const identifier = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/);
const checksum = z.string().regex(/^[a-f0-9]{64}$/);
const shortText = z.string().min(1).max(160);
const dateTime = z.string().refine((value) => !Number.isNaN(Date.parse(value)), {
  message: 'Expected an ISO-8601 date-time.',
});
const labelSchema = z.enum(['DEMO DATA', 'MEASURED DATA', 'MIXED DATA']);
const dataKindSchema = z.enum(['demo', 'measured', 'mixed']);
const reportPath = /^\/data\/v1\/reports\/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.[a-f0-9]{64}\.json$/;
const assetPath =
  /^\/data\/v1\/(?:reports\/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.[a-f0-9]{64}\.json|models\.[a-f0-9]{64}\.json|methodology\.[a-f0-9]{64}\.json)$/;

const measurementSchema = z.strictObject({
  value: z.number().nonnegative().finite().nullable(),
  unit: z.string().min(1).max(16),
  unavailable_reason: z
    .enum(['not_measured', 'unsupported', 'no_samples', 'worker_offline', 'api_unreachable'])
    .nullable(),
});
const millisecondsSchema = measurementSchema.extend({ unit: z.literal('ms') });
const throughputSchema = measurementSchema.extend({ unit: z.literal('tok/s') });
const memorySchema = measurementSchema.extend({ unit: z.literal('MiB') });
const qualitySchema = measurementSchema.extend({
  value: z.number().nonnegative().max(1).finite().nullable(),
  unit: z.literal('score'),
});

const runSchema = z.strictObject({
  id: identifier,
  experiment_id: identifier,
  attempt: z.number().int().min(1).max(2),
  state: z.literal('complete'),
  condition: z.enum(['warm', 'cold']),
  kind: z.literal('measured'),
  repetition: z.number().int().min(0).max(19),
  recorded_at: dateTime,
  input_tokens: z.number().int().min(0).nullable(),
  output_tokens: z.number().int().min(0).nullable(),
  ttft: millisecondsSchema,
  request_latency: millisecondsSchema,
  decode_throughput: throughputSchema,
  peak_vram: memorySchema,
  quality: qualitySchema,
  error_code: z.null(),
});

const summarySchema = z.strictObject({
  experiment_id: identifier,
  condition: z.enum(['warm', 'cold']),
  state: z.literal('complete'),
  accepted_run_ids: z.array(identifier).max(20),
  sample_count: z.number().int().min(0).max(20),
  error_count: z.number().int().min(0),
  ttft_median: millisecondsSchema,
  request_latency_p95: millisecondsSchema,
  decode_throughput: throughputSchema,
  peak_vram: memorySchema,
  quality: qualitySchema,
});

const hardwareSchema = z.strictObject({
  gpu_device_id: identifier,
  gpu_layers: z.number().int().min(0).max(200).nullable(),
  device_name: shortText,
  device_memory_mib: z.number().int().min(1),
  driver_version: shortText,
  gpu_settings: shortText,
});

const provenanceSchema = z.strictObject({
  engine: engineSchema,
  model: modelSchema,
  workload: workloadSchema,
  hardware: hardwareSchema,
  methodology_version: identifier,
});

export const publishedReportSchema = z
  .strictObject({
    id: identifier,
    title: shortText,
    description: z.string().min(1).max(500),
    category: shortText,
    publication_state: z.literal('published'),
    data_kind: z.enum(['demo', 'measured']),
    label: z.enum(['DEMO DATA', 'MEASURED DATA']),
    published_at: dateTime,
    config: experimentConfigSchema,
    provenance: provenanceSchema,
    summary: summarySchema,
    runs: z.array(runSchema).min(1).max(20),
    limitations: z.array(shortText).min(1).max(10),
  })
  .superRefine((report, context) => {
    if (report.config.experiment_id !== report.summary.experiment_id) {
      context.addIssue({
        code: 'custom',
        path: ['summary', 'experiment_id'],
        message: 'Report config and summary experiment identifiers disagree.',
      });
    }
    const expectedLabel = report.data_kind === 'demo' ? 'DEMO DATA' : 'MEASURED DATA';
    if (report.label !== expectedLabel) {
      context.addIssue({
        code: 'custom',
        path: ['label'],
        message: 'Report label must disclose the data kind.',
      });
    }
    const runIds = report.runs.map((run) => run.id);
    const accepted = report.summary.accepted_run_ids;
    if (
      new Set(runIds).size !== runIds.length ||
      runIds.length !== accepted.length ||
      runIds.some((id) => !accepted.includes(id))
    ) {
      context.addIssue({
        code: 'custom',
        path: ['runs'],
        message: 'Published runs must exactly match accepted summary run IDs.',
      });
    }
    for (const run of report.runs) {
      if (
        run.condition !== report.summary.condition ||
        run.experiment_id !== report.config.experiment_id
      ) {
        context.addIssue({
          code: 'custom',
          path: ['runs'],
          message: 'Report runs must share one experiment and condition.',
        });
      }
    }
  });

export const manifestReportSchema = z
  .strictObject({
    id: identifier,
    title: shortText,
    description: z.string().min(1).max(500),
    category: shortText,
    data_kind: z.enum(['demo', 'measured']),
    label: z.enum(['DEMO DATA', 'MEASURED DATA']),
    published_at: dateTime,
    experiment_id: identifier,
    engine_id: z.enum(['ollama', 'llama.cpp']),
    model_id: identifier,
    methodology_version: identifier,
    condition: z.enum(['warm', 'cold']),
    sample_count: z.number().int().min(0).max(20),
    path: z.string().regex(reportPath),
    sha256: checksum,
    size: z.number().int().min(1).max(5_242_880),
  })
  .superRefine((entry, context) => {
    if (entry.path !== `/data/v1/reports/${entry.id}.${entry.sha256}.json`) {
      context.addIssue({
        code: 'custom',
        path: ['path'],
        message: 'Report path must bind its identifier and checksum.',
      });
    }
  });

export const assetReferenceSchema = z.strictObject({
  path: z.string().regex(assetPath),
  sha256: checksum,
  size: z.number().int().min(1).max(5_242_880),
});

export const manifestSchema = z
  .strictObject({
    schema_version: z.literal('1.0'),
    release_id: identifier,
    published_at: dateTime,
    label: labelSchema,
    data_kind: dataKindSchema,
    report_count: z.number().int().min(0).max(100),
    reports: z.array(manifestReportSchema).max(100),
    models: assetReferenceSchema,
    methodology: assetReferenceSchema,
    limits: z.strictObject({
      max_reports: z.literal(100),
      max_files: z.literal(2000),
      max_asset_bytes: z.literal(5_242_880),
    }),
  })
  .superRefine((manifest, context) => {
    if (manifest.report_count !== manifest.reports.length) {
      context.addIssue({
        code: 'custom',
        path: ['report_count'],
        message: 'Manifest report count must match its entries.',
      });
    }
    const ids = manifest.reports.map((entry) => entry.id);
    const paths = manifest.reports.map((entry) => entry.path);
    if (new Set(ids).size !== ids.length || new Set(paths).size !== paths.length) {
      context.addIssue({
        code: 'custom',
        path: ['reports'],
        message: 'Manifest report identifiers and paths must be unique.',
      });
    }
    if (
      manifest.models.path === manifest.methodology.path ||
      paths.includes(manifest.models.path) ||
      paths.includes(manifest.methodology.path)
    ) {
      context.addIssue({
        code: 'custom',
        path: ['models'],
        message: 'Manifest asset paths must be unique.',
      });
    }
  });

export const modelsSnapshotSchema = z
  .strictObject({
    schema_version: z.literal('1.0'),
    label: labelSchema,
    models: z.array(modelSchema).max(100),
  })
  .superRefine((snapshot, context) => {
    const ids = snapshot.models.map((model) => model.id);
    if (new Set(ids).size !== ids.length) {
      context.addIssue({
        code: 'custom',
        path: ['models'],
        message: 'Snapshot model identifiers must be unique.',
      });
    }
  });

export const methodologyMetricSchema = z.strictObject({
  key: identifier,
  label: shortText,
  unit: shortText,
  direction: z.enum(['lower', 'higher', 'descriptive']),
  description: z.string().min(1).max(500),
});

export const methodologySnapshotSchema = z
  .strictObject({
    schema_version: z.literal('1.0'),
    methodology_versions: z.array(identifier).max(20),
    metrics: z.array(methodologyMetricSchema).min(1).max(20),
    conditions: z
      .array(z.enum(['warm', 'cold']))
      .min(1)
      .max(2),
    protocol: z.array(shortText).min(1).max(20),
    limitations: z.array(shortText).min(1).max(20),
  })
  .superRefine((snapshot, context) => {
    if (new Set(snapshot.methodology_versions).size !== snapshot.methodology_versions.length) {
      context.addIssue({
        code: 'custom',
        path: ['methodology_versions'],
        message: 'Methodology versions must be unique.',
      });
    }
  });

export type SnapshotManifest = z.infer<typeof manifestSchema>;
export type ModelsSnapshot = z.infer<typeof modelsSnapshotSchema>;
export type MethodologySnapshot = z.infer<typeof methodologySnapshotSchema>;
export type SnapshotReport = z.infer<typeof publishedReportSchema>;

export type SnapshotBundle = {
  manifest: SnapshotManifest;
  reports: SnapshotReport[];
  models: ModelsSnapshot;
  methodology: MethodologySnapshot;
};

export type SnapshotResources = Pick<
  ContractCatalog,
  'registry' | 'experiments' | 'runs' | 'summaries' | 'reports' | 'worker'
>;

export class SnapshotError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SnapshotError';
  }
}

function parseSchema<T>(schema: z.ZodType<T>, value: unknown, label: string): T {
  const result = schema.safeParse(value);
  if (!result.success) {
    const issue = result.error.issues[0];
    throw new SnapshotError(`${label} failed validation: ${issue?.message ?? 'unknown error'}`);
  }
  return result.data;
}

async function sha256(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
  const subtle = globalThis.crypto?.subtle;
  if (!subtle) throw new SnapshotError('Browser SHA-256 verification is unavailable.');
  const digest = await subtle.digest('SHA-256', bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function fetchAsset<T>(
  fetchImpl: typeof fetch,
  reference: { path: string; sha256: string; size: number },
  schema: z.ZodType<T>,
  label: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetchImpl(reference.path, {
    cache: 'force-cache',
    headers: { Accept: 'application/json' },
    ...(signal ? { signal } : {}),
  });
  if (!response.ok) {
    throw new SnapshotError(`${label} returned HTTP ${response.status}.`);
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.includes('application/json')) {
    throw new SnapshotError(`${label} did not return JSON.`);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes.byteLength !== reference.size) {
    throw new SnapshotError(`${label} size does not match the manifest.`);
  }
  if ((await sha256(bytes)) !== reference.sha256) {
    throw new SnapshotError(`${label} checksum does not match the manifest.`);
  }
  let raw: unknown;
  try {
    raw = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new SnapshotError(`${label} is not valid JSON.`);
  }
  return parseSchema(schema, raw, label);
}

function validateBundle(bundle: SnapshotBundle): void {
  const modelIds = new Set(bundle.models.models.map((model) => model.id));
  const versions = new Set(bundle.methodology.methodology_versions);
  if (bundle.reports.length > 0) {
    const kinds = new Set(bundle.reports.map((report) => report.data_kind));
    const first = bundle.reports[0];
    if (!first) throw new SnapshotError('Published release has no reports.');
    const expectedKind = kinds.size > 1 ? 'mixed' : first.data_kind;
    const expectedLabel =
      expectedKind === 'mixed'
        ? 'MIXED DATA'
        : expectedKind === 'demo'
          ? 'DEMO DATA'
          : 'MEASURED DATA';
    if (bundle.manifest.data_kind !== expectedKind || bundle.manifest.label !== expectedLabel) {
      throw new SnapshotError('Published manifest label does not match its reports.');
    }
    if (bundle.models.label !== expectedLabel) {
      throw new SnapshotError('Models snapshot label does not match the release.');
    }
  }
  for (const report of bundle.reports) {
    if (!modelIds.has(report.config.model_id)) {
      throw new SnapshotError(`Report ${report.id} references a model outside the release.`);
    }
    if (
      report.provenance.model.id !== report.config.model_id ||
      report.provenance.engine.id !== report.config.engine_id ||
      report.provenance.workload.id !== report.config.workload_id
    ) {
      throw new SnapshotError(`Report ${report.id} has inconsistent provenance.`);
    }
    if (bundle.reports.length > 0 && !versions.has(report.provenance.methodology_version)) {
      throw new SnapshotError(`Report ${report.id} references an unknown methodology version.`);
    }
  }
}

export async function loadPublishedSnapshot(
  fetchImpl: typeof fetch = fetch,
  signal?: AbortSignal,
): Promise<SnapshotBundle | null> {
  const response = await fetchImpl('/data/v1/manifest.json', {
    cache: 'no-cache',
    headers: { Accept: 'application/json' },
    ...(signal ? { signal } : {}),
  });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new SnapshotError(`Published manifest returned HTTP ${response.status}.`);
  }
  const contentType = response.headers.get('content-type')?.toLowerCase() ?? '';
  if (!contentType.includes('application/json')) return null;
  let raw: unknown;
  try {
    raw = JSON.parse(await response.text());
  } catch {
    throw new SnapshotError('Published manifest is not valid JSON.');
  }
  const manifest = parseSchema(manifestSchema, raw, 'Published manifest');
  const [models, methodology, reports] = await Promise.all([
    fetchAsset(fetchImpl, manifest.models, modelsSnapshotSchema, 'Models snapshot', signal),
    fetchAsset(
      fetchImpl,
      manifest.methodology,
      methodologySnapshotSchema,
      'Methodology snapshot',
      signal,
    ),
    Promise.all(
      manifest.reports.map(async (entry) => {
        const report = await fetchAsset(
          fetchImpl,
          entry,
          publishedReportSchema,
          `Report ${entry.id}`,
          signal,
        );
        if (
          report.id !== entry.id ||
          report.published_at !== entry.published_at ||
          report.config.experiment_id !== entry.experiment_id ||
          report.config.engine_id !== entry.engine_id ||
          report.config.model_id !== entry.model_id ||
          report.config.condition !== entry.condition ||
          report.provenance.methodology_version !== entry.methodology_version ||
          report.summary.sample_count !== entry.sample_count
        ) {
          throw new SnapshotError(`Report ${entry.id} does not match its manifest entry.`);
        }
        return report;
      }),
    ),
  ]);
  const bundle: SnapshotBundle = { manifest, models, methodology, reports };
  validateBundle(bundle);
  return bundle;
}

function uniqueById<T extends { id: string }>(items: T[], label: string): T[] {
  const unique = new Map<string, T>();
  for (const item of items) {
    const existing = unique.get(item.id);
    if (existing && JSON.stringify(existing) !== JSON.stringify(item)) {
      throw new SnapshotError(`Published ${label} metadata conflicts for ${item.id}.`);
    }
    unique.set(item.id, item);
  }
  return [...unique.values()].sort((left, right) => left.id.localeCompare(right.id));
}

function reportToExperiment(report: SnapshotReport): Experiment {
  const times = report.runs.map((run) => Date.parse(run.recorded_at));
  const published = Date.parse(report.published_at);
  const started = new Date(Math.min(published, ...times)).toISOString();
  const finished = new Date(Math.max(published, ...times)).toISOString();
  const job: Job = {
    id: report.id,
    experiment_id: report.config.experiment_id,
    state: 'complete',
    phase: 'completed',
    attempt: report.runs[0]?.attempt ?? 1,
    created_at: started,
    started_at: started,
    finished_at: finished,
    error_code: null,
    cancellation_requested: false,
  };
  return {
    id: report.config.experiment_id,
    name: report.title,
    config: report.config,
    provenance: report.provenance,
    job,
    summary: report.summary,
  };
}

export function toSnapshotResources(bundle: SnapshotBundle): SnapshotResources {
  const resourceLabel =
    bundle.manifest.label === 'MIXED DATA' ? 'MEASURED DATA' : bundle.manifest.label;
  const reports = [...bundle.reports].sort(
    (left, right) =>
      Date.parse(right.published_at) - Date.parse(left.published_at) ||
      left.id.localeCompare(right.id),
  );
  const engines = uniqueById(
    reports.map((report) => report.provenance.engine),
    'engine',
  );
  const workloads = uniqueById(
    reports.map((report) => report.provenance.workload),
    'workload',
  );
  const latestByExperiment = new Map<string, SnapshotReport>();
  for (const report of reports) {
    if (!latestByExperiment.has(report.config.experiment_id)) {
      latestByExperiment.set(report.config.experiment_id, report);
    }
  }
  const experiments = [...latestByExperiment.values()].map(reportToExperiment);
  const runs: RunMetrics[] = reports.flatMap((report) => report.runs);
  const summaries = reports.map((report) => report.summary);
  return {
    registry: {
      state: 'complete',
      label: resourceLabel,
      data: { engines, models: bundle.models.models, workloads },
    },
    experiments: {
      state: 'complete',
      label: resourceLabel,
      data: { items: experiments, next_cursor: null },
    },
    runs: { state: 'complete', label: resourceLabel, data: runs },
    summaries: { state: 'complete', label: resourceLabel, data: summaries },
    reports: {
      state: 'complete',
      label: resourceLabel,
      data: reports as PublishedReport[],
    },
    worker: {
      state: 'complete',
      label: resourceLabel,
      data: {
        availability: 'unknown',
        worker_id: 'snapshot',
        observed_at: bundle.manifest.published_at,
        last_seen_at: null,
        mode: null,
        active_job_id: null,
        paused: false,
      },
    },
  };
}
