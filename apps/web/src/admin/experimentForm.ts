import { experimentConfigSchema } from '@/api/schemas';
import type { ExperimentConfig, Registry } from '@/api/types';

const identifierPattern = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$/;

export interface ConfigDraft {
  name: string;
  experimentId: string;
  engineId: string;
  modelId: string;
  workloadId: string;
  condition: ExperimentConfig['condition'];
  contextTokens: string;
  inputTokenBudget: string;
  maxOutputTokens: string;
  temperature: string;
  topP: string;
  seed: string;
  warmups: string;
  repetitions: string;
  timeoutSeconds: string;
  gpuDeviceId: string;
  gpuLayers: string;
}

export type FieldErrors = Partial<Record<keyof ConfigDraft | 'form', string>>;

export function suggestExperimentId() {
  const suffix = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 7)}`;
  return `exp-${suffix}`.slice(0, 64);
}

export function modelsForEngine(registry: Registry, engineId: string) {
  return registry.models.filter((model) =>
    model.engine_ids.some((candidate) => candidate === engineId),
  );
}

export function initialDraft(registry: Registry): ConfigDraft {
  const engine =
    registry.engines.find((item) => item.availability === 'available') ?? registry.engines[0];
  const models = engine ? modelsForEngine(registry, engine.id) : [];
  const model = models[0];
  const workload = registry.workloads[0];
  const contextTokens = Math.max(128, Math.min(model?.max_context_tokens ?? 2048, 4096));
  const inputTokenBudget = Math.min(512, contextTokens - 1);
  const maxOutputTokens = Math.min(256, contextTokens - inputTokenBudget);

  return {
    name: '',
    experimentId: suggestExperimentId(),
    engineId: engine?.id ?? '',
    modelId: model?.id ?? '',
    workloadId: workload?.id ?? '',
    condition: 'warm',
    contextTokens: String(contextTokens),
    inputTokenBudget: String(inputTokenBudget),
    maxOutputTokens: String(maxOutputTokens),
    temperature: '0.2',
    topP: '0.9',
    seed: '',
    warmups: '1',
    repetitions: '3',
    timeoutSeconds: '300',
    gpuDeviceId: 'gpu-0',
    gpuLayers: '',
  };
}

function readInteger(
  value: string,
  field: keyof ConfigDraft,
  minimum: number,
  maximum: number,
  errors: FieldErrors,
) {
  const trimmed = value.trim();
  if (!/^-?\d+$/.test(trimmed)) {
    errors[field] = 'Enter a whole number.';
    return Number.NaN;
  }
  const parsed = Number(trimmed);
  if (parsed < minimum || parsed > maximum) {
    errors[field] = `Use a value from ${minimum} to ${maximum}.`;
  }
  return parsed;
}

function readDecimal(
  value: string,
  field: keyof ConfigDraft,
  minimum: number,
  maximum: number,
  errors: FieldErrors,
  inclusiveMinimum = true,
) {
  const trimmed = value.trim();
  if (!/^(?:\d+\.?\d*|\.\d+)$/.test(trimmed)) {
    errors[field] = 'Enter a number.';
    return Number.NaN;
  }
  const parsed = Number(trimmed);
  if (parsed < minimum || parsed > maximum || (!inclusiveMinimum && parsed === minimum)) {
    errors[field] = inclusiveMinimum
      ? `Use a value from ${minimum} to ${maximum}.`
      : `Use a value greater than ${minimum} and at most ${maximum}.`;
  }
  return parsed;
}

function fieldForContractPath(path: readonly PropertyKey[]) {
  switch (path[0]) {
    case 'experiment_id':
      return 'experimentId' as const;
    case 'context_tokens':
      return 'contextTokens' as const;
    case 'input_token_budget':
      return 'inputTokenBudget' as const;
    case 'max_output_tokens':
      return 'maxOutputTokens' as const;
    case 'temperature':
      return 'temperature' as const;
    case 'top_p':
      return 'topP' as const;
    case 'warmups':
      return 'warmups' as const;
    case 'repetitions':
      return 'repetitions' as const;
    case 'timeout_seconds':
      return 'timeoutSeconds' as const;
    case 'gpu_device_id':
      return 'gpuDeviceId' as const;
    case 'gpu_layers':
      return 'gpuLayers' as const;
    case 'sampling':
      return path[1] === 'top_p'
        ? ('topP' as const)
        : path[1] === 'seed'
          ? ('seed' as const)
          : ('temperature' as const);
    default:
      return 'form' as const;
  }
}

export function validateDraft(
  draft: ConfigDraft,
  registry: Registry,
): { config: ExperimentConfig | null; errors: FieldErrors } {
  const errors: FieldErrors = {};
  const name = draft.name.trim();
  const experimentId = draft.experimentId.trim();
  const engine = registry.engines.find((item) => item.id === draft.engineId);
  const model = registry.models.find((item) => item.id === draft.modelId);
  const workload = registry.workloads.find((item) => item.id === draft.workloadId);

  if (!name) errors.name = 'Enter an administrative name.';
  else if (name.length > 160) errors.name = 'Use 160 characters or fewer.';

  if (!identifierPattern.test(experimentId)) {
    errors.experimentId =
      'Use 1–64 letters, digits, dots, dashes, or underscores, starting with a letter or digit.';
  }

  if (!engine) {
    errors.engineId = 'Choose an inference engine.';
  } else if (engine.availability !== 'available') {
    errors.engineId = 'This engine is unavailable. Choose another or restore the runner.';
  }

  if (!model) {
    errors.modelId = 'Choose a model.';
  } else if (engine && !model.engine_ids.includes(engine.id)) {
    errors.modelId = 'This model does not support the selected engine.';
  }

  if (!workload) errors.workloadId = 'Choose a workload.';

  const contextTokens = readInteger(
    draft.contextTokens,
    'contextTokens',
    128,
    model?.max_context_tokens ?? 8192,
    errors,
  );
  const inputTokenBudget = readInteger(draft.inputTokenBudget, 'inputTokenBudget', 1, 8191, errors);
  const maxOutputTokens = readInteger(draft.maxOutputTokens, 'maxOutputTokens', 1, 2048, errors);
  if (
    Number.isFinite(contextTokens) &&
    Number.isFinite(inputTokenBudget) &&
    Number.isFinite(maxOutputTokens) &&
    inputTokenBudget + maxOutputTokens > contextTokens
  ) {
    errors.maxOutputTokens = 'Input and output budgets must fit within the context window.';
  }

  const temperature = readDecimal(draft.temperature, 'temperature', 0, 2, errors);
  const topP = readDecimal(draft.topP, 'topP', 0, 1, errors, false);
  const warmups = readInteger(draft.warmups, 'warmups', 0, 5, errors);
  const repetitions = readInteger(draft.repetitions, 'repetitions', 1, 20, errors);
  const timeoutSeconds = readInteger(draft.timeoutSeconds, 'timeoutSeconds', 1, 3600, errors);
  const gpuLayers = draft.gpuLayers.trim()
    ? readInteger(draft.gpuLayers, 'gpuLayers', 0, 200, errors)
    : null;
  const gpuDeviceId = draft.gpuDeviceId.trim();
  if (!identifierPattern.test(gpuDeviceId)) {
    errors.gpuDeviceId = 'Use a registry-approved GPU device identifier.';
  }

  if (draft.condition === 'cold' && warmups !== 0) {
    errors.warmups = 'Cold runs require zero warmups.';
  }

  let seed: number | null = null;
  if (!engine?.seed_supported && draft.seed.trim()) {
    errors.seed = 'The selected engine does not support deterministic seeds.';
  } else if (engine?.seed_supported && draft.seed.trim()) {
    seed = readInteger(draft.seed, 'seed', 0, 2147483647, errors);
  }

  if (Object.keys(errors).length || !engine || !model || !workload) {
    return { config: null, errors };
  }

  const candidate: ExperimentConfig = {
    experiment_id: experimentId,
    engine_id: engine.id,
    engine_version: engine.version,
    engine_build: engine.build,
    seed_supported: engine.seed_supported,
    model_id: model.id,
    model_revision: model.revision,
    model_sha256: model.sha256,
    quantization: model.quantization,
    workload_id: workload.id,
    prompt_id: workload.prompt_id,
    condition: draft.condition,
    context_tokens: contextTokens,
    input_token_budget: inputTokenBudget,
    max_output_tokens: maxOutputTokens,
    sampling: { temperature, top_p: topP, seed },
    warmups,
    repetitions,
    concurrency: 1,
    timeout_seconds: timeoutSeconds,
    gpu_device_id: gpuDeviceId,
    gpu_layers: gpuLayers,
  };

  const parsed = experimentConfigSchema.safeParse(candidate);
  if (!parsed.success) {
    for (const issue of parsed.error.issues) {
      const field = fieldForContractPath(issue.path);
      errors[field] ??= issue.message;
    }
    return { config: null, errors };
  }
  return { config: parsed.data, errors };
}
