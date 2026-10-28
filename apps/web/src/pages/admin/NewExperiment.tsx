import { AlertTriangle, Info, RotateCcw, Send } from 'lucide-react';
import { useRef, useState, type FormEvent, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { friendlyApiMessage } from '@/api/client';
import type { Registry } from '@/api/types';
import {
  initialDraft,
  modelsForEngine,
  validateDraft,
  type ConfigDraft,
} from '@/admin/experimentForm';
import { newIdempotencyKey, useCreateExperiment, useRegistryQuery } from '@/admin/queries';
import { PageHeading } from '@/components/PageHeading';
import { EmptyState } from '@/components/EmptyState';
import { ErrorState } from '@/components/ErrorState';
import { Skeleton } from '@/components/Skeleton';
import { WorkerStatusBanner } from '@/components/admin/WorkerStatusBanner';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

function normalizeBudgets(
  contextValue: string,
  inputValue: string,
  outputValue: string,
  maxContext: number,
) {
  const context = Math.min(Math.max(Number(contextValue) || maxContext, 128), maxContext);
  const input = Math.min(Math.max(Number(inputValue) || 512, 1), context - 1);
  const output = Math.min(Math.max(Number(outputValue) || 256, 1), context - input);
  return {
    contextTokens: String(context),
    inputTokenBudget: String(input),
    maxOutputTokens: String(output),
  };
}

interface TextFieldProps {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: (() => void) | undefined;
  error?: string | undefined;
  showError?: boolean | undefined;
  hint?: string | undefined;
  type?: 'text' | 'number';
  min?: number;
  max?: number;
  step?: number;
  maxLength?: number;
  inputMode?: 'text' | 'numeric' | 'decimal';
  disabled?: boolean;
  mono?: boolean;
  placeholder?: string;
}

function TextField({ id, showError, error, hint, mono, ...props }: TextFieldProps) {
  const describedBy =
    [hint ? `${id}-hint` : null, showError && error ? `${id}-error` : null]
      .filter(Boolean)
      .join(' ') || undefined;
  return (
    <div className="admin-field">
      <label htmlFor={id} className="admin-field-label">
        {props.label}
      </label>
      <input
        id={id}
        name={id}
        className={`admin-input${mono ? ' font-mono' : ''}`}
        type={props.type ?? 'text'}
        value={props.value}
        onChange={(event) => props.onChange(event.target.value)}
        onBlur={props.onBlur}
        min={props.min}
        max={props.max}
        step={props.step}
        maxLength={props.maxLength}
        inputMode={props.inputMode}
        disabled={props.disabled}
        placeholder={props.placeholder}
        aria-invalid={showError && error ? true : undefined}
        aria-describedby={describedBy}
      />
      {hint && !(showError && error) && (
        <p id={`${id}-hint`} className="admin-field-hint">
          {hint}
        </p>
      )}
      {showError && error && (
        <p id={`${id}-error`} className="admin-field-error">
          {error}
        </p>
      )}
    </div>
  );
}

function SelectField({
  id,
  label,
  value,
  onChange,
  onBlur,
  error,
  showError,
  hint,
  children,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  onBlur?: (() => void) | undefined;
  error?: string | undefined;
  showError?: boolean | undefined;
  hint?: string | undefined;
  children: ReactNode;
}) {
  return (
    <div className="admin-field">
      <label htmlFor={id} className="admin-field-label">
        {label}
      </label>
      <select
        id={id}
        name={id}
        className="native-select w-full"
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        aria-invalid={showError && error ? true : undefined}
        aria-describedby={
          [hint ? `${id}-hint` : null, showError && error ? `${id}-error` : null]
            .filter(Boolean)
            .join(' ') || undefined
        }
      >
        {children}
      </select>
      {hint && !(showError && error) && (
        <p id={`${id}-hint`} className="admin-field-hint">
          {hint}
        </p>
      )}
      {showError && error && (
        <p id={`${id}-error`} className="admin-field-error">
          {error}
        </p>
      )}
    </div>
  );
}

function SummaryRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function ConfigEditor({ registry }: { registry: Registry }) {
  const navigate = useNavigate();
  const create = useCreateExperiment();
  const [draft, setDraft] = useState<ConfigDraft>(() => initialDraft(registry));
  const [touched, setTouched] = useState<Set<keyof ConfigDraft>>(new Set());
  const [submitted, setSubmitted] = useState(false);
  const formRef = useRef<HTMLFormElement>(null);
  const keyRef = useRef<string | null>(null);
  const validation = validateDraft(draft, registry);
  const { config, errors } = validation;
  const errorCount = Object.keys(errors).length;
  const engine = registry.engines.find((item) => item.id === draft.engineId);
  const model = registry.models.find((item) => item.id === draft.modelId);
  const workload = registry.workloads.find((item) => item.id === draft.workloadId);
  const models = modelsForEngine(registry, draft.engineId);

  const show = (field: keyof ConfigDraft) => submitted || touched.has(field);
  const touch = (field: keyof ConfigDraft) =>
    setTouched((previous) => {
      if (previous.has(field)) return previous;
      const next = new Set(previous);
      next.add(field);
      return next;
    });
  const replace = (patch: Partial<ConfigDraft>) => {
    setDraft((previous) => ({ ...previous, ...patch }));
    keyRef.current = null;
  };
  const update = <K extends keyof ConfigDraft>(field: K, value: ConfigDraft[K]) => {
    replace({ [field]: value } as Pick<ConfigDraft, K>);
  };
  const changeContext = (nextModelId: string, current: ConfigDraft) => {
    const nextModel = registry.models.find((item) => item.id === nextModelId);
    return normalizeBudgets(
      current.contextTokens,
      current.inputTokenBudget,
      current.maxOutputTokens,
      nextModel?.max_context_tokens ?? 8192,
    );
  };

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (!config) {
      requestAnimationFrame(() => {
        formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
      });
      return;
    }
    keyRef.current ??= newIdempotencyKey();
    create.mutate(
      { name: draft.name.trim(), idempotency_key: keyRef.current, config },
      {
        onSuccess: (experiment) =>
          navigate(`/admin/experiments/${experiment.id}`, { state: { created: true } }),
      },
    );
  };

  const reset = () => {
    setDraft(initialDraft(registry));
    setTouched(new Set());
    setSubmitted(false);
    keyRef.current = null;
    create.reset();
  };

  const fieldError = (field: keyof ConfigDraft) => (show(field) ? errors[field] : undefined);

  return (
    <form ref={formRef} onSubmit={submit} noValidate>
      {submitted && errorCount > 0 && (
        <div className="admin-form-error mb-5" role="alert">
          <p>
            {errorCount} {errorCount === 1 ? 'field needs' : 'fields need'} attention. Review the
            highlighted values below.
          </p>
        </div>
      )}
      {create.error && (
        <div className="admin-form-error mb-5" role="alert">
          <p>{friendlyApiMessage(create.error)}</p>
        </div>
      )}

      <fieldset disabled={create.isPending} className="admin-form-fieldset">
        <div className="admin-form-layout">
          <div className="space-y-5">
            <section className="admin-card" aria-labelledby="identity-heading">
              <div className="admin-card-header">
                <div>
                  <h2 id="identity-heading" className="section-title">
                    Identity
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    The ID is permanent. The name is administrative and can be renamed later.
                  </p>
                </div>
              </div>
              <div className="grid gap-4 p-5 sm:grid-cols-2">
                <TextField
                  id="name"
                  label="Administrative name"
                  value={draft.name}
                  onChange={(value) => update('name', value)}
                  onBlur={() => touch('name')}
                  error={fieldError('name')}
                  showError={show('name')}
                  maxLength={160}
                  placeholder="Baseline context warm run"
                />
                <TextField
                  id="experiment-id"
                  label="Experiment ID"
                  value={draft.experimentId}
                  onChange={(value) => update('experimentId', value)}
                  onBlur={() => touch('experimentId')}
                  error={fieldError('experimentId')}
                  showError={show('experimentId')}
                  maxLength={64}
                  mono
                  hint="1–64 letters, digits, dots, dashes, or underscores. Immutable after queueing."
                />
              </div>
            </section>

            <section className="admin-card" aria-labelledby="runner-heading">
              <div className="admin-card-header">
                <div>
                  <h2 id="runner-heading" className="section-title">
                    Runner selections
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Only registry-approved IDs are accepted. Pins are resolved automatically and
                    cannot be edited.
                  </p>
                </div>
              </div>
              <div className="grid gap-4 p-5 sm:grid-cols-2">
                <SelectField
                  id="engine"
                  label="Engine"
                  value={draft.engineId}
                  onChange={(value) => {
                    const nextEngine = registry.engines.find((item) => item.id === value);
                    const nextModels = modelsForEngine(registry, value);
                    const nextModel =
                      nextModels.find((item) => item.id === draft.modelId) ?? nextModels[0];
                    replace({
                      engineId: value,
                      modelId: nextModel?.id ?? '',
                      seed: nextEngine?.seed_supported ? draft.seed : '',
                      ...changeContext(nextModel?.id ?? '', draft),
                    });
                  }}
                  onBlur={() => touch('engineId')}
                  error={fieldError('engineId')}
                  showError={show('engineId')}
                  hint={
                    engine
                      ? `${engine.version} · build ${engine.build} · ${engine.availability}`
                      : 'Choose an available local engine.'
                  }
                >
                  <option value="" disabled>
                    Choose engine
                  </option>
                  {registry.engines.map((item) => (
                    <option
                      key={item.id}
                      value={item.id}
                      disabled={item.availability !== 'available'}
                    >
                      {item.name} ({item.id})
                      {item.availability !== 'available' ? ' — unavailable' : ''}
                    </option>
                  ))}
                </SelectField>
                <SelectField
                  id="model"
                  label="Model"
                  value={draft.modelId}
                  onChange={(value) => {
                    replace({ modelId: value, ...changeContext(value, draft) });
                  }}
                  onBlur={() => touch('modelId')}
                  error={fieldError('modelId')}
                  showError={show('modelId')}
                  hint={
                    model
                      ? `${model.parameter_size} · ${model.quantization} · ${model.max_context_tokens.toLocaleString()} token maximum`
                      : 'No model supports the selected engine.'
                  }
                >
                  <option value="" disabled>
                    Choose model
                  </option>
                  {models.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name} ({item.quantization})
                    </option>
                  ))}
                </SelectField>
                <SelectField
                  id="workload"
                  label="Workload"
                  value={draft.workloadId}
                  onChange={(value) => update('workloadId', value)}
                  onBlur={() => touch('workloadId')}
                  error={fieldError('workloadId')}
                  showError={show('workloadId')}
                  hint={workload ? `Prompt ${workload.prompt_id}` : 'Choose an approved workload.'}
                >
                  <option value="" disabled>
                    Choose workload
                  </option>
                  {registry.workloads.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.id} ({item.data_policy})
                    </option>
                  ))}
                </SelectField>
                <SelectField
                  id="condition"
                  label="Condition"
                  value={draft.condition}
                  onChange={(value) => {
                    const condition = value as ConfigDraft['condition'];
                    replace({
                      condition,
                      ...(condition === 'cold' ? { warmups: '0' } : {}),
                    });
                  }}
                  hint={
                    draft.condition === 'cold'
                      ? 'Cold runs require zero warmups.'
                      : 'Warmups run before the measured repetitions.'
                  }
                >
                  <option value="warm">Warm</option>
                  <option value="cold">Cold</option>
                </SelectField>
              </div>
            </section>

            <section className="admin-card" aria-labelledby="budgets-heading">
              <div className="admin-card-header">
                <div>
                  <h2 id="budgets-heading" className="section-title">
                    Token budgets
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Input and maximum output must fit within the context window.
                  </p>
                </div>
              </div>
              <div className="grid gap-4 p-5 sm:grid-cols-3">
                <TextField
                  id="context-tokens"
                  label="Context (tokens)"
                  type="number"
                  inputMode="numeric"
                  min={128}
                  max={model?.max_context_tokens ?? 8192}
                  step={1}
                  value={draft.contextTokens}
                  onChange={(value) => update('contextTokens', value)}
                  onBlur={() => touch('contextTokens')}
                  error={fieldError('contextTokens')}
                  showError={show('contextTokens')}
                  hint={`128–${(model?.max_context_tokens ?? 8192).toLocaleString()}`}
                />
                <TextField
                  id="input-budget"
                  label="Input budget (tokens)"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={8191}
                  step={1}
                  value={draft.inputTokenBudget}
                  onChange={(value) => update('inputTokenBudget', value)}
                  onBlur={() => touch('inputTokenBudget')}
                  error={fieldError('inputTokenBudget')}
                  showError={show('inputTokenBudget')}
                  hint="Prompt allowance"
                />
                <TextField
                  id="output-budget"
                  label="Max output (tokens)"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={2048}
                  step={1}
                  value={draft.maxOutputTokens}
                  onChange={(value) => update('maxOutputTokens', value)}
                  onBlur={() => touch('maxOutputTokens')}
                  error={fieldError('maxOutputTokens')}
                  showError={show('maxOutputTokens')}
                  hint="Generation cap"
                />
              </div>
              <div className="px-5 pb-5">
                <p className="budget-meter">
                  {draft.inputTokenBudget || '0'} input + {draft.maxOutputTokens || '0'} output
                  against {draft.contextTokens || '0'} context tokens
                </p>
              </div>
            </section>

            <section className="admin-card" aria-labelledby="sampling-heading">
              <div className="admin-card-header">
                <div>
                  <h2 id="sampling-heading" className="section-title">
                    Sampling
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Keep the deterministic defaults unless the workload calls for variation.
                  </p>
                </div>
              </div>
              <div className="grid gap-4 p-5 sm:grid-cols-3">
                <TextField
                  id="temperature"
                  label="Temperature"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  max={2}
                  step={0.01}
                  value={draft.temperature}
                  onChange={(value) => update('temperature', value)}
                  onBlur={() => touch('temperature')}
                  error={fieldError('temperature')}
                  showError={show('temperature')}
                  hint="0–2"
                />
                <TextField
                  id="top-p"
                  label="Top-p"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  max={1}
                  step={0.01}
                  value={draft.topP}
                  onChange={(value) => update('topP', value)}
                  onBlur={() => touch('topP')}
                  error={fieldError('topP')}
                  showError={show('topP')}
                  hint="Greater than 0, up to 1"
                />
                <TextField
                  id="seed"
                  label="Seed (optional)"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={2147483647}
                  step={1}
                  value={draft.seed}
                  onChange={(value) => update('seed', value)}
                  onBlur={() => touch('seed')}
                  error={fieldError('seed')}
                  showError={show('seed')}
                  disabled={!engine?.seed_supported}
                  hint={
                    engine?.seed_supported
                      ? 'Leave blank for a non-deterministic run.'
                      : 'The selected engine does not support seeds.'
                  }
                />
              </div>
            </section>

            <section className="admin-card" aria-labelledby="execution-heading">
              <div className="admin-card-header">
                <div>
                  <h2 id="execution-heading" className="section-title">
                    Execution and hardware
                  </h2>
                  <p className="mt-1 text-xs text-muted-foreground">
                    Runs execute sequentially. GPU device pins must match the local runner.
                  </p>
                </div>
              </div>
              <div className="grid gap-4 p-5 sm:grid-cols-3">
                <TextField
                  id="warmups"
                  label="Warmups"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={5}
                  step={1}
                  value={draft.warmups}
                  onChange={(value) => update('warmups', value)}
                  onBlur={() => touch('warmups')}
                  error={fieldError('warmups')}
                  showError={show('warmups')}
                  disabled={draft.condition === 'cold'}
                  hint={draft.condition === 'cold' ? 'Fixed at zero' : '0–5'}
                />
                <TextField
                  id="repetitions"
                  label="Measured repetitions"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={20}
                  step={1}
                  value={draft.repetitions}
                  onChange={(value) => update('repetitions', value)}
                  onBlur={() => touch('repetitions')}
                  error={fieldError('repetitions')}
                  showError={show('repetitions')}
                  hint="1–20"
                />
                <TextField
                  id="timeout"
                  label="Timeout (seconds)"
                  type="number"
                  inputMode="numeric"
                  min={1}
                  max={3600}
                  step={1}
                  value={draft.timeoutSeconds}
                  onChange={(value) => update('timeoutSeconds', value)}
                  onBlur={() => touch('timeoutSeconds')}
                  error={fieldError('timeoutSeconds')}
                  showError={show('timeoutSeconds')}
                  hint="1–3600"
                />
                <TextField
                  id="gpu-device"
                  label="GPU device ID"
                  value={draft.gpuDeviceId}
                  onChange={(value) => update('gpuDeviceId', value)}
                  onBlur={() => touch('gpuDeviceId')}
                  error={fieldError('gpuDeviceId')}
                  showError={show('gpuDeviceId')}
                  maxLength={64}
                  mono
                  hint="For example, gpu-0 from the local runner policy."
                />
                <TextField
                  id="gpu-layers"
                  label="GPU layers (optional)"
                  type="number"
                  inputMode="numeric"
                  min={0}
                  max={200}
                  step={1}
                  value={draft.gpuLayers}
                  onChange={(value) => update('gpuLayers', value)}
                  onBlur={() => touch('gpuLayers')}
                  error={fieldError('gpuLayers')}
                  showError={show('gpuLayers')}
                  hint="Leave blank for the runner default."
                />
              </div>
            </section>
          </div>

          <aside className="admin-form-aside" aria-label="Submission summary">
            <div className="admin-card admin-sticky-card">
              <div className="admin-card-header">
                <h2 className="section-title">Queue summary</h2>
                <Badge variant="outline">NOT RUN</Badge>
              </div>
              <div className="p-5">
                <dl className="summary-list">
                  <SummaryRow
                    label="Engine"
                    value={engine ? `${engine.name} ${engine.version}` : '—'}
                  />
                  <SummaryRow
                    label="Model"
                    value={model ? `${model.name} (${model.quantization})` : '—'}
                  />
                  <SummaryRow label="Workload" value={workload?.id ?? '—'} />
                  <SummaryRow
                    label="Runs"
                    value={`${Number(draft.warmups) || 0} warmup + ${Number(draft.repetitions) || 0} measured`}
                  />
                  <SummaryRow
                    label="Budget"
                    value={`${draft.inputTokenBudget || 0} in / ${draft.maxOutputTokens || 0} out of ${draft.contextTokens || 0}`}
                  />
                  <SummaryRow label="Condition" value={draft.condition} />
                  <SummaryRow
                    label="Model SHA-256"
                    value={
                      <span className="break-all font-mono text-[10px]">
                        {model?.sha256 ?? '—'}
                      </span>
                    }
                  />
                </dl>

                <div className="admin-inline-alert mt-4" role="note">
                  <Info size={16} aria-hidden="true" />
                  <p>
                    Submitting only validates and queues a job. Completion is shown only after the
                    worker and API confirm it.
                  </p>
                </div>

                {errorCount > 0 && submitted && (
                  <div className="admin-inline-alert admin-inline-alert-error mt-3" role="alert">
                    <AlertTriangle size={16} aria-hidden="true" />
                    <p>Fix the highlighted fields before queueing.</p>
                  </div>
                )}

                <Button type="submit" className="mt-4 w-full" disabled={create.isPending}>
                  <Send size={15} aria-hidden="true" />
                  {create.isPending ? 'Queueing…' : 'Queue experiment'}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  className="mt-2 w-full"
                  onClick={reset}
                  disabled={create.isPending}
                >
                  <RotateCcw size={14} aria-hidden="true" />
                  Reset form
                </Button>
              </div>
            </div>
          </aside>
        </div>
      </fieldset>
    </form>
  );
}

export function NewExperiment() {
  const registry = useRegistryQuery();

  if (registry.isPending) return <Skeleton label="Loading runner registry" />;
  if (registry.error) {
    return (
      <ErrorState
        onRetry={() => void registry.refetch()}
        title="Unable to load the runner registry"
        description={friendlyApiMessage(registry.error)}
        actionLabel="Retry"
      />
    );
  }

  const data = registry.data;
  const availableEngine = data?.engines.find((engine) => engine.availability === 'available');
  const compatibleModels = availableEngine ? modelsForEngine(data!, availableEngine.id) : [];

  if (!data || !availableEngine || !compatibleModels.length || !data.workloads.length) {
    return (
      <>
        <title>New experiment · InferLab Admin</title>
        <PageHeading
          eyebrow="LOCAL ADMIN"
          title="New experiment"
          description="Submissions require an available engine, a compatible registry model, and an approved workload."
          titleSuffix="InferLab admin"
        />
        <EmptyState
          title="The local runner is not ready for submissions"
          description="The API is reachable, but its registry has no available engine with a compatible model and workload. Configure the runner, then refresh."
          action={
            <Button variant="outline" onClick={() => void registry.refetch()}>
              Refresh registry
            </Button>
          }
        />
      </>
    );
  }

  return (
    <>
      <title>New experiment · InferLab Admin</title>
      <PageHeading
        eyebrow="LOCAL ADMIN"
        title="New experiment"
        description="Select approved runner pins, bound the workload, and queue a job. Nothing is downloaded or installed from this form."
        titleSuffix="InferLab admin"
        action={
          <Button variant="outline" onClick={() => void registry.refetch()}>
            Refresh registry
          </Button>
        }
      />
      <WorkerStatusBanner />
      <ConfigEditor registry={data} />
    </>
  );
}
