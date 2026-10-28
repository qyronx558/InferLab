import { z } from 'zod';
import type { ExperimentConfig, Job, Registry } from './types';

const identifier = z.string().regex(/^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/);
const checksum = z.string().regex(/^[a-f0-9]{64}$/);
const shortText = z.string().min(1).max(160);
const dateTime = z.string().refine((value) => !Number.isNaN(Date.parse(value)), {
  message: 'Expected an ISO-8601 date-time.',
});

export const engineIdSchema = z.enum(['ollama', 'llama.cpp']);
export const quantizationSchema = z.enum(['Q4_K_M', 'Q5_K_M', 'Q8_0', 'FP16']);
export const jobPhaseSchema = z.enum([
  'queued',
  'leased',
  'running',
  'completed',
  'failed',
  'cancelled',
]);
export const jobStateSchema = z.enum(['pending', 'running', 'complete', 'failed', 'cancelled']);

export const errorCodeSchema = z.enum([
  'validation_error',
  'worker_lost',
  'engine_unavailable',
  'out_of_memory',
  'timeout',
  'cancelled',
]);

const samplingSchema = z.strictObject({
  temperature: z.number().min(0).max(2),
  top_p: z.number().gt(0).max(1),
  seed: z.number().int().min(0).max(2147483647).nullable(),
});

export const experimentConfigSchema: z.ZodType<ExperimentConfig> = z
  .strictObject({
    experiment_id: identifier,
    engine_id: engineIdSchema,
    engine_version: shortText,
    engine_build: shortText,
    seed_supported: z.boolean(),
    model_id: identifier,
    model_revision: identifier,
    model_sha256: checksum,
    quantization: quantizationSchema,
    workload_id: identifier,
    prompt_id: identifier,
    condition: z.enum(['warm', 'cold']),
    context_tokens: z.number().int().min(128).max(8192),
    input_token_budget: z.number().int().min(1).max(8191),
    max_output_tokens: z.number().int().min(1).max(2048),
    sampling: samplingSchema,
    warmups: z.number().int().min(0).max(5),
    repetitions: z.number().int().min(1).max(20),
    concurrency: z.literal(1),
    timeout_seconds: z.number().int().min(1).max(3600),
    gpu_device_id: identifier,
    gpu_layers: z.number().int().min(0).max(200).nullable(),
  })
  .superRefine((config, context) => {
    if (config.input_token_budget + config.max_output_tokens > config.context_tokens) {
      context.addIssue({
        code: 'custom',
        path: ['max_output_tokens'],
        message: 'Input and output token budgets must fit within the context window.',
      });
    }
    if (config.condition === 'cold' && config.warmups !== 0) {
      context.addIssue({
        code: 'custom',
        path: ['warmups'],
        message: 'Cold runs require zero warmups.',
      });
    }
    if (config.sampling.seed !== null && !config.seed_supported) {
      context.addIssue({
        code: 'custom',
        path: ['sampling', 'seed'],
        message: 'The selected engine does not support deterministic seeds.',
      });
    }
  });

const phaseStates: Record<z.infer<typeof jobPhaseSchema>, z.infer<typeof jobStateSchema>> = {
  queued: 'pending',
  leased: 'pending',
  running: 'running',
  completed: 'complete',
  failed: 'failed',
  cancelled: 'cancelled',
};

export const jobSchema: z.ZodType<Job> = z
  .strictObject({
    id: identifier,
    experiment_id: identifier,
    state: jobStateSchema,
    phase: jobPhaseSchema,
    attempt: z.number().int().min(0).max(2),
    created_at: dateTime,
    started_at: dateTime.nullable(),
    finished_at: dateTime.nullable(),
    error_code: errorCodeSchema.nullable(),
    cancellation_requested: z.boolean(),
  })
  .superRefine((job, context) => {
    if (phaseStates[job.phase] !== job.state) {
      context.addIssue({ code: 'custom', path: ['state'], message: 'Job state/phase disagree.' });
    }
    const terminal = ['completed', 'failed', 'cancelled'].includes(job.phase);
    if (terminal !== (job.finished_at !== null)) {
      context.addIssue({
        code: 'custom',
        path: ['finished_at'],
        message: 'Terminal jobs must have a finish time; active jobs must not.',
      });
    }
    if (['running', 'completed'].includes(job.phase) && job.started_at === null) {
      context.addIssue({
        code: 'custom',
        path: ['started_at'],
        message: 'Started phases require a start time.',
      });
    }
    if (job.phase === 'failed' && job.error_code === null) {
      context.addIssue({
        code: 'custom',
        path: ['error_code'],
        message: 'Failed jobs require an error code.',
      });
    }
    if (job.phase === 'completed' && (job.error_code !== null || job.cancellation_requested)) {
      context.addIssue({
        code: 'custom',
        path: ['state'],
        message: 'Completed jobs cannot have an error or cancellation request.',
      });
    }
  });

export const experimentResourceSchema = z.strictObject({
  id: identifier,
  name: shortText,
  version: z.number().int().min(1),
  archived_at: dateTime.nullable(),
  config: experimentConfigSchema,
  job: jobSchema,
});

export type LiveExperiment = z.infer<typeof experimentResourceSchema>;

export const experimentPageSchema = z.strictObject({
  items: z.array(experimentResourceSchema),
  next_cursor: identifier.nullable(),
});

export type LiveExperimentPage = z.infer<typeof experimentPageSchema>;

const engineSchema = z.strictObject({
  id: engineIdSchema,
  name: shortText,
  version: shortText,
  build: shortText,
  availability: z.enum(['available', 'unavailable']),
  seed_supported: z.boolean(),
});

const modelSchema = z.strictObject({
  id: identifier,
  name: shortText,
  parameter_size: shortText,
  revision: identifier,
  sha256: checksum,
  quantization: quantizationSchema,
  engine_ids: z.array(engineIdSchema).min(1).max(2),
  max_context_tokens: z.number().int().min(128).max(8192),
  license_name: shortText,
});

const workloadSchema = z.strictObject({
  id: identifier,
  prompt_id: identifier,
  sha256: checksum,
  data_policy: z.enum(['public', 'synthetic']),
  license_name: shortText,
});

export const registrySchema: z.ZodType<Registry> = z
  .strictObject({
    engines: z.array(engineSchema).max(2),
    models: z.array(modelSchema).max(100),
    workloads: z.array(workloadSchema).max(100),
  })
  .superRefine((registry, context) => {
    for (const [name, items] of [
      ['engines', registry.engines],
      ['models', registry.models],
      ['workloads', registry.workloads],
    ] as const) {
      const ids = items.map((item) => item.id);
      if (new Set(ids).size !== ids.length) {
        context.addIssue({ code: 'custom', path: [name], message: `Duplicate ${name} IDs.` });
      }
    }
  });

export const sessionInfoSchema = z.strictObject({
  identity: z.literal('admin'),
  csrf_token: z.string().regex(/^[a-f0-9]{64}$/),
  expires_at: dateTime,
});

export type SessionInfo = z.infer<typeof sessionInfoSchema>;

export const workerHeartbeatSchema = z
  .strictObject({
    availability: z.enum(['online', 'offline', 'unknown']),
    worker_id: identifier,
    observed_at: dateTime,
    last_seen_at: dateTime.nullable(),
    mode: z.enum(['idle', 'running']).nullable(),
    active_job_id: identifier.nullable(),
    paused: z.boolean(),
  })
  .superRefine((worker, context) => {
    if (worker.availability === 'unknown') {
      if (worker.mode !== null || worker.active_job_id !== null) {
        context.addIssue({
          code: 'custom',
          path: ['availability'],
          message: 'Unknown worker status cannot claim live execution.',
        });
      }
      return;
    }
    if (worker.last_seen_at === null) {
      context.addIssue({
        code: 'custom',
        path: ['last_seen_at'],
        message: 'Known worker status requires a last-seen time.',
      });
      return;
    }
    const age = Date.parse(worker.observed_at) - Date.parse(worker.last_seen_at);
    if ((worker.availability === 'online') !== age <= 90_000) {
      context.addIssue({
        code: 'custom',
        path: ['availability'],
        message: 'Worker availability must follow the 90-second heartbeat threshold.',
      });
    }
    if (
      worker.availability === 'offline' &&
      (worker.mode !== null || worker.active_job_id !== null)
    ) {
      context.addIssue({
        code: 'custom',
        path: ['availability'],
        message: 'Offline workers cannot report a live job.',
      });
    }
    if (
      worker.availability === 'online' &&
      (worker.mode === null || (worker.mode === 'running') !== (worker.active_job_id !== null))
    ) {
      context.addIssue({
        code: 'custom',
        path: ['mode'],
        message: 'Online mode and active job must agree.',
      });
    }
  });

export type WorkerStatus = z.infer<typeof workerHeartbeatSchema>;

export const errorEnvelopeSchema = z.strictObject({
  error: z.strictObject({
    code: z.string(),
    message: z.string(),
    request_id: z.string(),
  }),
});

export const emptySchema = z.null();
