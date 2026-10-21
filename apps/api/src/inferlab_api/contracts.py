"""Wire contracts only. No execution, metric calculation, persistence or HTTP routes."""

from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
Checksum = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=160)]
Count = Annotated[int, Field(strict=True, ge=0)]
FiniteValue = Annotated[float, Field(strict=True, ge=0)]
EngineID = Literal["ollama", "llama.cpp"]
Quantization = Literal["Q4_K_M", "Q5_K_M", "Q8_0", "FP16"]
ExecutionState = Literal["unavailable", "pending", "running", "complete", "failed", "cancelled"]
JobPhase = Literal["queued", "leased", "running", "completed", "failed", "cancelled"]
UnavailableReason = Literal[
    "not_measured", "unsupported", "no_samples", "worker_offline", "api_unreachable"
]
ErrorCode = Literal[
    "validation_error", "worker_lost", "engine_unavailable", "out_of_memory", "timeout", "cancelled"
]

PHASE_STATES: dict[JobPhase, ExecutionState] = {
    "queued": "pending",
    "leased": "pending",
    "running": "running",
    "completed": "complete",
    "failed": "failed",
    "cancelled": "cancelled",
}


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, validate_default=True)


class Engine(Contract):
    id: EngineID
    name: ShortText
    version: ShortText
    build: ShortText
    availability: Literal["available", "unavailable"]
    seed_supported: Annotated[bool, Field(strict=True)]


class Model(Contract):
    id: Identifier
    name: ShortText
    parameter_size: ShortText
    revision: Identifier
    sha256: Checksum
    quantization: Quantization
    engine_ids: Annotated[list[EngineID], Field(min_length=1, max_length=2)]
    max_context_tokens: Annotated[int, Field(strict=True, ge=128, le=8192)]
    license_name: ShortText


class Workload(Contract):
    id: Identifier
    prompt_id: Identifier
    sha256: Checksum
    data_policy: Literal["public", "synthetic"]
    license_name: ShortText


class Registry(Contract):
    engines: Annotated[list[Engine], Field(max_length=2)]
    models: Annotated[list[Model], Field(max_length=100)]
    workloads: Annotated[list[Workload], Field(max_length=100)]

    @model_validator(mode="after")
    def unique_ids(self) -> Self:
        for entries in (self.engines, self.models, self.workloads):
            ids = [entry.id for entry in entries]
            if len(set(ids)) != len(ids):
                raise ValueError("Registry identifiers must be unique")
        return self


class Sampling(Contract):
    temperature: Annotated[float, Field(strict=True, ge=0, le=2)]
    top_p: Annotated[float, Field(strict=True, gt=0, le=1)]
    seed: Annotated[int, Field(strict=True, ge=0, le=2147483647)] | None


class ExperimentConfig(Contract):
    experiment_id: Identifier
    engine_id: EngineID
    engine_version: ShortText
    engine_build: ShortText
    seed_supported: Annotated[bool, Field(strict=True)]
    model_id: Identifier
    model_revision: Identifier
    model_sha256: Checksum
    quantization: Quantization
    workload_id: Identifier
    prompt_id: Identifier
    condition: Literal["warm", "cold"]
    context_tokens: Annotated[int, Field(strict=True, ge=128, le=8192)]
    input_token_budget: Annotated[int, Field(strict=True, ge=1, le=8191)]
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=2048)]
    sampling: Sampling
    warmups: Annotated[int, Field(strict=True, ge=0, le=5)]
    repetitions: Annotated[int, Field(strict=True, ge=1, le=20)]
    concurrency: Annotated[int, Field(strict=True, ge=1, le=1)]
    timeout_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)]
    gpu_device_id: Identifier
    gpu_layers: Annotated[int, Field(strict=True, ge=0, le=200)] | None

    @model_validator(mode="after")
    def bounded_workload(self) -> Self:
        if self.input_token_budget + self.max_output_tokens > self.context_tokens:
            raise ValueError("Input and output budgets must fit the context")
        if self.condition == "cold" and self.warmups != 0:
            raise ValueError("Cold experiments must not request warmups")
        if self.sampling.seed is not None and not self.seed_supported:
            raise ValueError("Engine does not support a seed")
        return self


class ExperimentSubmitRequest(Contract):
    name: ShortText
    idempotency_key: Identifier
    config: ExperimentConfig


def validate_submission(request: ExperimentSubmitRequest, registry: Registry) -> None:
    """Resolve allowlisted IDs/capabilities; never execute or install anything."""
    config = request.config
    engine = next((item for item in registry.engines if item.id == config.engine_id), None)
    model = next((item for item in registry.models if item.id == config.model_id), None)
    if engine is None or model is None:
        raise ValueError("Unknown engine or model")
    if engine.id not in model.engine_ids:
        raise ValueError("Model does not support this engine")
    workload = next((item for item in registry.workloads if item.id == config.workload_id), None)
    if workload is None:
        raise ValueError("Unknown workload")
    if config.sampling.seed is not None and not engine.seed_supported:
        raise ValueError("Engine does not support a seed")
    _validate_pins(config, engine, model, workload)


class Job(Contract):
    id: Identifier
    experiment_id: Identifier
    # Availability is an envelope concern, never a persisted job phase.
    state: Literal["pending", "running", "complete", "failed", "cancelled"]
    phase: JobPhase
    attempt: Annotated[int, Field(strict=True, ge=0, le=2)]
    created_at: AwareDatetime
    started_at: AwareDatetime | None
    finished_at: AwareDatetime | None
    error_code: ErrorCode | None
    cancellation_requested: bool

    @model_validator(mode="after")
    def coherent_state(self) -> Self:
        if self.state != PHASE_STATES[self.phase]:
            raise ValueError("Job display state must match its lifecycle phase")
        terminal = self.state in ("complete", "failed", "cancelled")
        if terminal != (self.finished_at is not None):
            raise ValueError("Terminal jobs require a finish time; active jobs must not have one")
        if self.state in ("running", "complete") and self.started_at is None:
            raise ValueError("Running and completed jobs require a start time")
        if self.state == "failed" and self.error_code is None:
            raise ValueError("Failed jobs require an error code")
        if self.state == "complete" and self.error_code is not None:
            raise ValueError("Completed jobs cannot have an error")
        if self.state == "complete" and self.cancellation_requested:
            raise ValueError("A cancellation request cannot be committed before completion")
        if self.phase in ("leased", "running", "completed", "failed") and self.attempt == 0:
            raise ValueError("A claimed job requires an attempt number")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("Start precedes creation")
        if self.finished_at is not None and self.finished_at < (self.started_at or self.created_at):
            raise ValueError("Finish precedes start or creation")
        return self


class Measurement(Contract):
    value: FiniteValue | None
    unavailable_reason: UnavailableReason | None

    @model_validator(mode="after")
    def explicit_missing_value(self) -> Self:
        if (self.value is None) != (self.unavailable_reason is not None):
            raise ValueError("A null value needs a reason; an available value cannot have one")
        return self


class Milliseconds(Measurement):
    unit: Literal["ms"]


class TokensPerSecond(Measurement):
    unit: Literal["tok/s"]


class MemoryMiB(Measurement):
    unit: Literal["MiB"]


class QualityScore(Measurement):
    unit: Literal["score"]
    value: Annotated[float, Field(strict=True, ge=0, le=1)] | None


class Hardware(Contract):
    gpu_device_id: Identifier
    gpu_layers: Annotated[int, Field(strict=True, ge=0, le=200)] | None
    device_name: ShortText
    device_memory_mib: Annotated[int, Field(strict=True, ge=1)]
    driver_version: ShortText
    gpu_settings: ShortText


class Provenance(Contract):
    engine: Engine
    model: Model
    workload: Workload
    hardware: Hardware
    methodology_version: Identifier


def _validate_pins(
    config: ExperimentConfig, engine: Engine, model: Model, workload: Workload
) -> None:
    """Check declared identity against resolved/observed metadata, without I/O."""
    if (
        config.engine_id != engine.id
        or config.engine_version != engine.version
        or config.engine_build != engine.build
        or config.seed_supported != engine.seed_supported
    ):
        raise ValueError("Engine provenance does not match pinned config")
    if (
        config.model_id != model.id
        or config.model_revision != model.revision
        or config.model_sha256 != model.sha256
        or config.quantization != model.quantization
    ):
        raise ValueError("Model provenance does not match pinned config")
    if config.workload_id != workload.id or config.prompt_id != workload.prompt_id:
        raise ValueError("Prompt/workload provenance does not match pinned config")
    if engine.id not in model.engine_ids or config.context_tokens > model.max_context_tokens:
        raise ValueError("Model/engine context capability mismatch")


def _validate_provenance(config: ExperimentConfig, provenance: Provenance) -> None:
    _validate_pins(config, provenance.engine, provenance.model, provenance.workload)
    if (
        config.gpu_device_id != provenance.hardware.gpu_device_id
        or config.gpu_layers != provenance.hardware.gpu_layers
    ):
        raise ValueError("GPU settings do not match config")


class RunMetrics(Contract):
    id: Identifier
    experiment_id: Identifier
    attempt: Annotated[int, Field(strict=True, ge=1, le=2)]
    state: Literal["complete", "failed", "cancelled"]
    condition: Literal["warm", "cold"]
    kind: Literal["warmup", "measured"]
    repetition: Annotated[int, Field(strict=True, ge=0, le=19)]
    recorded_at: AwareDatetime
    input_tokens: Count | None
    output_tokens: Count | None
    ttft: Milliseconds
    request_latency: Milliseconds
    decode_throughput: TokensPerSecond
    peak_vram: MemoryMiB
    quality: QualityScore
    error_code: ErrorCode | None

    @model_validator(mode="after")
    def completion_error(self) -> Self:
        if self.state == "complete" and self.error_code is not None:
            raise ValueError("A completed run cannot contain an error")
        if self.state == "complete" and (self.input_tokens is None or self.output_tokens is None):
            raise ValueError("Completed runs require recorded token counts")
        if self.state == "failed" and self.error_code is None:
            raise ValueError("A failed run needs an error code")
        return self


class ResultError(Contract):
    """Safe diagnostic vocabulary; raw exceptions, paths and prompts stay local."""

    code: ErrorCode
    stage: Literal["preparation", "generation", "validation", "cleanup"]


class Result(Contract):
    """One run's reproducible record, not a summary, execution request or publication."""

    schema_version: Literal["1.0"]
    experiment_id: Identifier
    data_kind: Literal["demo", "measured"]
    label: Literal["DEMO DATA", "MEASURED DATA"]
    config: ExperimentConfig
    provenance: Provenance
    run: RunMetrics
    errors: Annotated[list[ResultError], Field(max_length=10)]

    @model_validator(mode="after")
    def consistent_evidence(self) -> Self:
        expected_label = "DEMO DATA" if self.data_kind == "demo" else "MEASURED DATA"
        if self.label != expected_label:
            raise ValueError("Result label must disclose the data kind")
        if self.experiment_id != self.config.experiment_id or (
            self.experiment_id != self.run.experiment_id
        ):
            raise ValueError("Result, config and run experiment identifiers disagree")
        _validate_provenance(self.config, self.provenance)
        if self.run.condition != self.config.condition:
            raise ValueError("Run condition must match config")
        limit = self.config.warmups if self.run.kind == "warmup" else self.config.repetitions
        if self.run.repetition >= limit:
            raise ValueError("Run index exceeds configured warmups or repetitions")
        if self.run.input_tokens is not None and (
            self.run.input_tokens > self.config.input_token_budget
        ):
            raise ValueError("Recorded input exceeds the configured budget")
        if self.run.output_tokens is not None and (
            self.run.output_tokens > self.config.max_output_tokens
        ):
            raise ValueError("Recorded output exceeds the configured budget")
        if (
            self.run.ttft.value is not None
            and self.run.request_latency.value is not None
            and self.run.ttft.value > self.run.request_latency.value
        ):
            raise ValueError("TTFT exceeds request latency")
        if self.run.state == "complete" and self.errors:
            raise ValueError("Complete results cannot contain errors")
        if self.run.state != "complete" and (
            not self.errors or self.run.error_code not in {error.code for error in self.errors}
        ):
            raise ValueError("Failed/cancelled results require the primary run error")
        if self.run.state == "cancelled" and self.run.error_code != "cancelled":
            raise ValueError("Cancelled results require the cancelled error code")
        if self.run.state == "failed" and self.run.error_code == "cancelled":
            raise ValueError("Cancellation must use the cancelled state")
        return self


class Summary(Contract):
    experiment_id: Identifier
    condition: Literal["warm", "cold"]
    state: Literal["unavailable", "complete"]
    accepted_run_ids: Annotated[list[Identifier], Field(max_length=20)]
    sample_count: Annotated[int, Field(strict=True, ge=0, le=20)]
    error_count: Count
    ttft_median: Milliseconds
    request_latency_p95: Milliseconds
    decode_throughput: TokensPerSecond
    peak_vram: MemoryMiB
    quality: QualityScore

    @model_validator(mode="after")
    def traceable_samples(self) -> Self:
        if len(set(self.accepted_run_ids)) != len(self.accepted_run_ids):
            raise ValueError("Summary run IDs must be unique")
        if self.sample_count != len(self.accepted_run_ids):
            raise ValueError("Sample count must match accepted run IDs")
        if (self.state == "complete") != (self.sample_count > 0):
            raise ValueError("Complete summaries require accepted samples")
        if self.state == "unavailable" and any(
            metric.value is not None
            for metric in (
                self.ttft_median,
                self.request_latency_p95,
                self.decode_throughput,
                self.peak_vram,
                self.quality,
            )
        ):
            raise ValueError("Unavailable summaries must not contain measurements")
        return self


class Experiment(Contract):
    id: Identifier
    name: ShortText
    config: ExperimentConfig
    provenance: Provenance
    job: Job
    summary: Summary

    @model_validator(mode="after")
    def consistent_links(self) -> Self:
        if self.config.experiment_id != self.id:
            raise ValueError("Config and experiment identifiers disagree")
        _validate_provenance(self.config, self.provenance)
        if self.job.experiment_id != self.id or self.summary.experiment_id != self.id:
            raise ValueError("Experiment, job and summary identifiers disagree")
        if self.config.condition != self.summary.condition:
            raise ValueError("Summary must use the experiment condition")
        if self.config.model_id != self.provenance.model.id:
            raise ValueError("Model provenance must match config")
        if self.config.engine_id != self.provenance.engine.id:
            raise ValueError("Engine provenance must match config")
        if self.config.workload_id != self.provenance.workload.id:
            raise ValueError("Workload provenance must match config")
        if self.job.state != "complete" and self.summary.state == "complete":
            raise ValueError("Only a complete job can have an accepted summary")
        return self


class ExperimentPage(Contract):
    items: Annotated[list[Experiment], Field(max_length=100)]
    next_cursor: Identifier | None


class PublishedReport(Contract):
    id: Identifier
    title: ShortText
    description: Annotated[str, Field(min_length=1, max_length=500)]
    category: ShortText
    publication_state: Literal["published"]
    data_kind: Literal["demo", "measured"]
    label: Literal["DEMO DATA", "MEASURED DATA"]
    published_at: AwareDatetime
    config: ExperimentConfig
    provenance: Provenance
    summary: Summary
    runs: Annotated[list[RunMetrics], Field(min_length=1, max_length=20)]
    limitations: Annotated[list[ShortText], Field(min_length=1, max_length=10)]

    @model_validator(mode="after")
    def publication_evidence(self) -> Self:
        if self.config.experiment_id != self.summary.experiment_id:
            raise ValueError("Report config and summary experiment identifiers disagree")
        _validate_provenance(self.config, self.provenance)
        expected = "DEMO DATA" if self.data_kind == "demo" else "MEASURED DATA"
        if self.label != expected:
            raise ValueError("Report label must disclose the data kind")
        if self.summary.state != "complete":
            raise ValueError("A report requires a complete summary")
        ids = [run.id for run in self.runs]
        if len(set(ids)) != len(ids) or set(ids) != set(self.summary.accepted_run_ids):
            raise ValueError("Published runs must exactly match accepted summary run IDs")
        if len({run.attempt for run in self.runs}) != 1:
            raise ValueError("A report must not mix attempts")
        if len({run.repetition for run in self.runs}) != len(self.runs):
            raise ValueError("Published repetition indices must be unique")
        for run in self.runs:
            if run.state != "complete" or run.kind != "measured":
                raise ValueError("Only completed measured runs may be published")
            if (
                run.condition != self.summary.condition
                or run.experiment_id != self.summary.experiment_id
            ):
                raise ValueError("Report must not mix experiment or condition")
            if run.repetition >= self.config.repetitions:
                raise ValueError("Run repetition is outside the configured bounds")
            if run.output_tokens is not None and run.output_tokens > self.config.max_output_tokens:
                raise ValueError("Recorded output exceeds the configured budget")
        if self.config.condition != self.summary.condition:
            raise ValueError("Report config and summary conditions disagree")
        if self.config.model_id != self.provenance.model.id:
            raise ValueError("Report model provenance mismatch")
        if self.config.engine_id != self.provenance.engine.id:
            raise ValueError("Report engine provenance mismatch")
        if self.config.workload_id != self.provenance.workload.id:
            raise ValueError("Report workload provenance mismatch")
        if self.summary.sample_count > self.config.repetitions:
            raise ValueError("Report samples exceed the configured repetition bound")
        return self


class WorkerHeartbeat(Contract):
    availability: Literal["online", "offline", "unknown"]
    worker_id: Identifier
    observed_at: AwareDatetime
    last_seen_at: AwareDatetime | None
    mode: Literal["idle", "running"] | None
    active_job_id: Identifier | None
    paused: bool

    @model_validator(mode="after")
    def heartbeat_consistency(self) -> Self:
        if self.last_seen_at is not None and self.last_seen_at > self.observed_at:
            raise ValueError("Last seen cannot be in the future")
        if self.availability == "unknown":
            if self.mode is not None or self.active_job_id is not None:
                raise ValueError("Unknown availability cannot claim live execution")
            return self
        if self.last_seen_at is None:
            raise ValueError("Known worker availability needs a last-seen time")
        age_seconds = (self.observed_at - self.last_seen_at).total_seconds()
        if (self.availability == "online") != (age_seconds <= 90):
            raise ValueError("Availability must follow the 90-second heartbeat threshold")
        if self.availability == "offline":
            if self.mode is not None or self.active_job_id is not None:
                raise ValueError("Offline worker must not imply a live job")
        elif self.mode is None or (self.mode == "running") != (self.active_job_id is not None):
            raise ValueError("Online mode and active job must agree")
        return self


class SubmissionReceipt(Contract):
    experiment_id: Identifier
    job_id: Identifier
    state: Literal["pending"]
    phase: Literal["queued"]


class Available[T](Contract):
    state: Literal["complete"]
    label: Literal["DEMO DATA", "MEASURED DATA"]
    data: T


class Unavailable(Contract):
    state: Literal["unavailable"]
    reason: Literal["worker_offline", "api_unreachable"]
    data: None


type Resource[T] = Annotated[Available[T] | Unavailable, Field(discriminator="state")]


class ContractCatalog(Contract):
    """Schema roots and a fully validated synthetic wire-fixture bundle."""

    schema_version: Literal["1.0"]
    label: Literal["DEMO DATA"]
    registry: Resource[Registry]
    experiments: Resource[ExperimentPage]
    runs: Resource[list[RunMetrics]]
    results: Resource[list[Result]]
    summaries: Resource[list[Summary]]
    reports: Resource[list[PublishedReport]]
    worker: Resource[WorkerHeartbeat]
    submit_request: ExperimentSubmitRequest
    submit_response: SubmissionReceipt
    job_scenarios: Annotated[list[Job], Field(min_length=6, max_length=6)]
    unavailable_response: Unavailable
    # Named display vocabulary remains explicit in the generated schema.
    display_states: Annotated[list[ExecutionState], Field(min_length=6, max_length=6)]
