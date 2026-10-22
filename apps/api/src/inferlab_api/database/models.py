"""Relational evidence and lifecycle shape, without queue or benchmark execution."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.orm import DeclarativeBase, Mapped, Mapper, mapped_column

from inferlab_api.contracts import PublishedReport as ReportContract

from .types import SHA256, FiniteMeasurement, Identifier, ReportSnapshot, UTCDateTime

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
ERROR_CODES = (
    "validation_error",
    "worker_lost",
    "engine_unavailable",
    "out_of_memory",
    "timeout",
    "cancelled",
)
REASONS = ("not_measured", "unsupported", "no_samples", "worker_offline", "api_unreachable")


def utc_now() -> datetime:
    return datetime.now(UTC)


def choice(name: str, *values: str) -> sa.Enum:
    return sa.Enum(
        *values, name=name, native_enum=False, create_constraint=True, validate_strings=True
    )


class Base(DeclarativeBase):
    metadata = sa.MetaData(naming_convention=NAMING)


class ModelRegistry(Base):
    __tablename__ = "model_registry"
    __table_args__ = (
        sa.UniqueConstraint(
            "id", "revision", "sha256", "quantization", name="uq_model_registry_pin"
        ),
        sa.CheckConstraint("length(sha256) = 64 AND sha256 = lower(sha256)", name="checksum_shape"),
        sa.CheckConstraint("max_context_tokens BETWEEN 128 AND 8192", name="context_bounds"),
        sa.Index("ix_model_registry_revision_quantization", "revision", "quantization"),
    )

    id: Mapped[str] = mapped_column(Identifier(), primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(160))
    revision: Mapped[str] = mapped_column(Identifier())
    sha256: Mapped[str] = mapped_column(SHA256())
    quantization: Mapped[str] = mapped_column(
        choice("quantization_values", "Q4_K_M", "Q5_K_M", "Q8_0", "FP16")
    )
    max_context_tokens: Mapped[int] = mapped_column(sa.Integer)
    license_name: Mapped[str] = mapped_column(sa.String(160))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["model_id", "model_revision", "model_sha256", "quantization"],
            [
                "model_registry.id",
                "model_registry.revision",
                "model_registry.sha256",
                "model_registry.quantization",
            ],
            name="fk_experiments_model_pin",
            ondelete="RESTRICT",
            onupdate="RESTRICT",
        ),
        sa.UniqueConstraint("id", "condition", name="uq_experiments_condition"),
        sa.CheckConstraint("context_tokens BETWEEN 128 AND 8192", name="context_bounds"),
        sa.CheckConstraint(
            "input_token_budget BETWEEN 1 AND 8191 AND max_output_tokens BETWEEN 1 AND 2048",
            name="token_bounds",
        ),
        sa.CheckConstraint(
            "input_token_budget + max_output_tokens <= context_tokens", name="context_budget"
        ),
        sa.CheckConstraint(
            "warmups BETWEEN 0 AND 5 AND repetitions BETWEEN 1 AND 20 AND concurrency = 1",
            name="execution_bounds",
        ),
        sa.CheckConstraint("condition != 'cold' OR warmups = 0", name="cold_warmups"),
        sa.CheckConstraint(
            "temperature BETWEEN 0 AND 2 AND top_p > 0 AND top_p <= 1", name="sampling_bounds"
        ),
        sa.CheckConstraint(
            "seed IS NULL OR (seed BETWEEN 0 AND 2147483647 AND seed_supported)",
            name="seed_support",
        ),
        sa.CheckConstraint(
            "gpu_layers IS NULL OR gpu_layers BETWEEN 0 AND 200", name="gpu_layers_bounds"
        ),
        sa.CheckConstraint("timeout_seconds BETWEEN 1 AND 3600", name="timeout_bounds"),
        sa.Index("ix_experiments_model_created", "model_id", "created_at"),
        sa.Index("ix_experiments_prompt_created", "prompt_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(Identifier(), primary_key=True)
    model_id: Mapped[str] = mapped_column(Identifier())
    model_revision: Mapped[str] = mapped_column(Identifier())
    model_sha256: Mapped[str] = mapped_column(SHA256())
    quantization: Mapped[str] = mapped_column(sa.String(16))
    engine_id: Mapped[str] = mapped_column(choice("engine_values", "ollama", "llama.cpp"))
    engine_version: Mapped[str] = mapped_column(sa.String(160))
    engine_build: Mapped[str] = mapped_column(sa.String(160))
    seed_supported: Mapped[bool] = mapped_column(
        sa.Boolean(create_constraint=True, name="seed_boolean")
    )
    workload_id: Mapped[str] = mapped_column(Identifier())
    workload_sha256: Mapped[str] = mapped_column(SHA256())
    prompt_id: Mapped[str] = mapped_column(Identifier())
    condition: Mapped[str] = mapped_column(choice("condition_values", "warm", "cold"))
    context_tokens: Mapped[int] = mapped_column(sa.Integer)
    input_token_budget: Mapped[int] = mapped_column(sa.Integer)
    max_output_tokens: Mapped[int] = mapped_column(sa.Integer)
    temperature: Mapped[float] = mapped_column(FiniteMeasurement())
    top_p: Mapped[float] = mapped_column(FiniteMeasurement())
    seed: Mapped[int | None] = mapped_column(sa.Integer)
    warmups: Mapped[int] = mapped_column(sa.Integer)
    repetitions: Mapped[int] = mapped_column(sa.Integer)
    concurrency: Mapped[int] = mapped_column(sa.Integer)
    timeout_seconds: Mapped[int] = mapped_column(sa.Integer)
    gpu_device_id: Mapped[str] = mapped_column(Identifier())
    gpu_layers: Mapped[int | None] = mapped_column(sa.Integer)
    device_name: Mapped[str] = mapped_column(sa.String(160))
    driver_version: Mapped[str] = mapped_column(sa.String(160))
    methodology_version: Mapped[str] = mapped_column(Identifier())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        sa.UniqueConstraint("id", "experiment_id", name="uq_jobs_experiment"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("active_slot", name="uq_jobs_single_active_slot"),
        sa.CheckConstraint("attempt BETWEEN 0 AND 2", name="attempt_bounds"),
        sa.CheckConstraint(
            "(phase IN ('leased', 'running') AND active_slot = 1 AND active_slot IS NOT NULL) "
            "OR (phase NOT IN ('leased', 'running') AND active_slot IS NULL)",
            name="active_slot_state",
        ),
        sa.CheckConstraint(
            "(phase IN ('completed', 'failed', 'cancelled') AND finished_at IS NOT NULL) "
            "OR (phase NOT IN ('completed', 'failed', 'cancelled') AND finished_at IS NULL)",
            name="terminal_time",
        ),
        sa.CheckConstraint(
            "phase NOT IN ('running', 'completed') OR started_at IS NOT NULL", name="start_required"
        ),
        sa.CheckConstraint(
            "phase NOT IN ('leased', 'running', 'completed', 'failed') OR attempt >= 1",
            name="claimed_attempt",
        ),
        sa.CheckConstraint("phase != 'failed' OR error_code IS NOT NULL", name="failure_error"),
        sa.CheckConstraint(
            "phase != 'completed' OR (error_code IS NULL AND NOT cancellation_requested)",
            name="complete_without_error",
        ),
        sa.CheckConstraint("started_at IS NULL OR started_at >= created_at", name="ordered_start"),
        sa.CheckConstraint(
            "finished_at IS NULL OR finished_at >= coalesce(started_at, created_at)",
            name="ordered_finish",
        ),
        sa.CheckConstraint(
            "(phase IN ('leased', 'running') AND worker_id IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND fencing_token > 0 "
            "AND fencing_token IS NOT NULL) "
            "OR (phase NOT IN ('leased', 'running') AND lease_expires_at IS NULL)",
            name="lease_shape",
        ),
        sa.Index("ix_jobs_queue", "phase", "created_at"),
        sa.Index("ix_jobs_experiment", "experiment_id", "created_at"),
        sa.Index("ix_jobs_lease_expiry", "lease_expires_at"),
    )

    id: Mapped[str] = mapped_column(Identifier(), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        Identifier(), sa.ForeignKey("experiments.id", ondelete="RESTRICT")
    )
    idempotency_key: Mapped[str] = mapped_column(Identifier())
    request_sha256: Mapped[str] = mapped_column(SHA256())
    phase: Mapped[str] = mapped_column(
        choice("phase_values", "queued", "leased", "running", "completed", "failed", "cancelled")
    )
    attempt: Mapped[int] = mapped_column(sa.Integer, default=0)
    active_slot: Mapped[int | None] = mapped_column(sa.Integer)
    worker_id: Mapped[str | None] = mapped_column(Identifier())
    fencing_token: Mapped[int | None] = mapped_column(sa.BigInteger)
    lease_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    error_code: Mapped[str | None] = mapped_column(choice("error_values", *ERROR_CODES))
    cancellation_requested: Mapped[bool] = mapped_column(
        sa.Boolean(create_constraint=True, name="cancel_boolean"), default=False
    )


def measurement_constraints() -> list[sa.CheckConstraint]:
    constraints: list[sa.CheckConstraint] = []
    for field in (
        "ttft_ms",
        "request_latency_ms",
        "decode_tokens_per_second",
        "peak_vram_mib",
        "quality_score",
    ):
        reason = field + "_reason"
        upper = 1 if field == "quality_score" else 1e15
        constraints.extend(
            [
                sa.CheckConstraint(
                    f"{field} IS NULL OR ({field} >= 0 AND {field} <= {upper})",
                    name=field + "_bounds",
                ),
                sa.CheckConstraint(
                    f"({field} IS NULL AND {reason} IS NOT NULL) "
                    f"OR ({field} IS NOT NULL AND {reason} IS NULL)",
                    name=field + "_availability",
                ),
            ]
        )
    return constraints


class RunMetric(Base):
    __tablename__ = "run_metrics"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["job_id", "experiment_id"],
            ["jobs.id", "jobs.experiment_id"],
            name="fk_runs_job_experiment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id", "condition"],
            ["experiments.id", "experiments.condition"],
            name="fk_runs_experiment_condition",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_id", "attempt", "kind", "repetition", name="uq_run_repetition"),
        sa.UniqueConstraint("id", "experiment_id", name="uq_runs_experiment"),
        sa.CheckConstraint(
            "attempt BETWEEN 1 AND 2 AND repetition BETWEEN 0 AND 19", name="run_bounds"
        ),
        sa.CheckConstraint(
            "(input_tokens IS NULL OR input_tokens >= 0) "
            "AND (output_tokens IS NULL OR output_tokens >= 0)",
            name="token_counts",
        ),
        sa.CheckConstraint(
            "state != 'complete' OR (input_tokens IS NOT NULL "
            "AND output_tokens IS NOT NULL AND error_code IS NULL)",
            name="complete_counts",
        ),
        sa.CheckConstraint("state != 'failed' OR error_code IS NOT NULL", name="failure_error"),
        sa.CheckConstraint(
            "state != 'cancelled' OR error_code = 'cancelled' AND error_code IS NOT NULL",
            name="cancelled_error",
        ),
        sa.CheckConstraint(
            "ttft_ms IS NULL OR request_latency_ms IS NULL OR ttft_ms <= request_latency_ms",
            name="ttft_order",
        ),
        sa.CheckConstraint(
            "(trace_sha256 IS NULL AND trace_bytes IS NULL AND trace_expires_at IS NULL) "
            "OR (trace_sha256 IS NOT NULL AND trace_bytes >= 0 "
            "AND trace_bytes IS NOT NULL AND trace_expires_at IS NOT NULL)",
            name="trace_reference",
        ),
        *measurement_constraints(),
        sa.Index("ix_runs_experiment_state", "experiment_id", "state", "recorded_at"),
        sa.Index("ix_runs_trace_expiry", "trace_expires_at"),
    )

    id: Mapped[str] = mapped_column(Identifier(), primary_key=True)
    job_id: Mapped[str] = mapped_column(Identifier())
    experiment_id: Mapped[str] = mapped_column(Identifier())
    attempt: Mapped[int] = mapped_column(sa.Integer)
    kind: Mapped[str] = mapped_column(choice("kind_values", "warmup", "measured"))
    repetition: Mapped[int] = mapped_column(sa.Integer)
    condition: Mapped[str] = mapped_column(choice("condition_values", "warm", "cold"))
    state: Mapped[str] = mapped_column(
        choice("run_state_values", "complete", "failed", "cancelled")
    )
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime())
    input_tokens: Mapped[int | None] = mapped_column(sa.BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(sa.BigInteger)
    error_code: Mapped[str | None] = mapped_column(choice("error_values", *ERROR_CODES))
    ttft_ms: Mapped[float | None] = mapped_column(FiniteMeasurement())
    ttft_ms_reason: Mapped[str | None] = mapped_column(choice("ttft_reason_values", *REASONS))
    request_latency_ms: Mapped[float | None] = mapped_column(FiniteMeasurement())
    request_latency_ms_reason: Mapped[str | None] = mapped_column(
        choice("latency_reason_values", *REASONS)
    )
    decode_tokens_per_second: Mapped[float | None] = mapped_column(FiniteMeasurement())
    decode_tokens_per_second_reason: Mapped[str | None] = mapped_column(
        choice("decode_reason_values", *REASONS)
    )
    peak_vram_mib: Mapped[float | None] = mapped_column(FiniteMeasurement())
    peak_vram_mib_reason: Mapped[str | None] = mapped_column(choice("vram_reason_values", *REASONS))
    quality_score: Mapped[float | None] = mapped_column(FiniteMeasurement())
    quality_score_reason: Mapped[str | None] = mapped_column(
        choice("quality_reason_values", *REASONS)
    )
    trace_sha256: Mapped[str | None] = mapped_column(SHA256())
    trace_bytes: Mapped[int | None] = mapped_column(sa.BigInteger)
    trace_expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class PublishedReport(Base):
    __tablename__ = "published_reports"
    __table_args__ = (
        sa.UniqueConstraint("payload_sha256"),
        sa.UniqueConstraint("id", "experiment_id", name="uq_reports_experiment"),
        sa.CheckConstraint("length(payload_sha256) = 64", name="payload_hash_shape"),
        sa.Index("ix_reports_experiment_published", "experiment_id", "published_at"),
    )

    id: Mapped[str] = mapped_column(Identifier(), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        Identifier(), sa.ForeignKey("experiments.id", ondelete="RESTRICT")
    )
    payload_sha256: Mapped[str] = mapped_column(SHA256())
    payload: Mapped[dict[str, Any]] = mapped_column(ReportSnapshot())
    published_at: Mapped[datetime] = mapped_column(UTCDateTime())


published_report_runs = sa.Table(
    "published_report_runs",
    Base.metadata,
    sa.Column("report_id", Identifier(), primary_key=True),
    sa.Column("run_id", Identifier(), primary_key=True),
    sa.Column("experiment_id", Identifier(), nullable=False),
    sa.ForeignKeyConstraint(
        ["report_id", "experiment_id"],
        ["published_reports.id", "published_reports.experiment_id"],
        name="fk_report_runs_report",
        ondelete="RESTRICT",
    ),
    sa.ForeignKeyConstraint(
        ["run_id", "experiment_id"],
        ["run_metrics.id", "run_metrics.experiment_id"],
        name="fk_report_runs_run",
        ondelete="RESTRICT",
    ),
    sa.Index("ix_published_report_runs_run", "run_id"),
)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        sa.Index("ix_audit_retention", "recorded_at"),
        sa.Index("ix_audit_subject", "subject_type", "subject_id", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(Identifier(), primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    actor: Mapped[str] = mapped_column(choice("actor_values", "admin", "worker", "system"))
    action: Mapped[str] = mapped_column(
        choice(
            "action_values",
            "login",
            "submit",
            "cancel",
            "retry",
            "pause",
            "resume",
            "publish",
            "withdraw",
            "retention",
            "update",
            "delete",
            "logout",
        )
    )
    outcome: Mapped[str] = mapped_column(choice("outcome_values", "success", "failure"))
    subject_type: Mapped[str] = mapped_column(
        choice("subject_values", "experiment", "job", "report", "system")
    )
    subject_id: Mapped[str] = mapped_column(Identifier())
    reason_code: Mapped[str | None] = mapped_column(
        choice("audit_reason_values", *ERROR_CODES, "invalid_credentials", "unauthorized")
    )


class ExperimentMetadata(Base):
    """Mutable administrative labels; benchmark evidence remains immutable."""

    __tablename__ = "experiment_metadata"
    __table_args__ = (sa.CheckConstraint("version >= 1", name="version_positive"),)
    experiment_id: Mapped[str] = mapped_column(
        Identifier(), sa.ForeignKey("experiments.id", ondelete="RESTRICT"), primary_key=True
    )
    name: Mapped[str] = mapped_column(sa.String(160))
    version: Mapped[int] = mapped_column(sa.Integer, default=1)
    archived_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class APIControl(Base):
    """One database-serialized admission/rate-limit row, shared by API processes."""

    __tablename__ = "api_control"
    __table_args__ = (sa.CheckConstraint("id = 1", name="singleton"),)
    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(sa.BigInteger)
    login_window: Mapped[datetime] = mapped_column(UTCDateTime())
    failed_logins: Mapped[int] = mapped_column(sa.Integer)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
    mutation_window: Mapped[datetime] = mapped_column(UTCDateTime())
    mutation_count: Mapped[int] = mapped_column(sa.Integer)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    token_sha256: Mapped[str] = mapped_column(SHA256(), primary_key=True)
    csrf_token: Mapped[str] = mapped_column(sa.String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)


class APIRequest(Base):
    """Durable idempotency tombstones: never store raw request bodies or passwords."""

    __tablename__ = "api_requests"
    key: Mapped[str] = mapped_column(Identifier(), primary_key=True)
    request_sha256: Mapped[str] = mapped_column(SHA256())
    response: Mapped[dict[str, Any]] = mapped_column(sa.JSON)
    status_code: Mapped[int] = mapped_column(sa.Integer)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)


def report_payload_sha256(payload: object) -> str:
    report = ReportContract.model_validate(payload)
    encoded = json.dumps(
        report.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@sa.event.listens_for(PublishedReport, "before_insert")
def validate_report_evidence(
    mapper: Mapper[PublishedReport], connection: Connection, report: PublishedReport
) -> None:
    """ORM integrity only; insertion neither approves nor deploys a publication."""
    payload = ReportContract.model_validate(report.payload)
    if payload.id != report.id or payload.summary.experiment_id != report.experiment_id:
        raise ValueError("Report row and payload identifiers disagree")
    if (
        payload.published_at != report.published_at
        or report_payload_sha256(report.payload) != report.payload_sha256
    ):
        raise ValueError("Report timestamp or payload checksum disagrees")
    experiment = (
        connection.execute(
            sa.select(Experiment.__table__).where(Experiment.id == report.experiment_id)
        )
        .mappings()
        .one_or_none()
    )
    if experiment is None:
        raise ValueError("Report experiment does not exist")
    config = payload.config.model_dump(exclude={"experiment_id", "sampling"})
    config.update(payload.config.sampling.model_dump())
    if any(experiment[key] != value for key, value in config.items()):
        raise ValueError("Report config does not match stored experiment")
    if payload.provenance.workload.sha256 != experiment["workload_sha256"] or (
        payload.provenance.methodology_version != experiment["methodology_version"]
        or payload.provenance.hardware.device_name != experiment["device_name"]
        or payload.provenance.hardware.driver_version != experiment["driver_version"]
    ):
        raise ValueError("Report provenance does not match stored experiment")
    metric_columns = {
        "ttft": "ttft_ms",
        "request_latency": "request_latency_ms",
        "decode_throughput": "decode_tokens_per_second",
        "peak_vram": "peak_vram_mib",
        "quality": "quality_score",
    }
    job_ids: set[str] = set()
    for run in payload.runs:
        stored = (
            connection.execute(sa.select(RunMetric.__table__).where(RunMetric.id == run.id))
            .mappings()
            .one_or_none()
        )
        if stored is None:
            raise ValueError("Accepted report run does not exist")
        scalars = run.model_dump(exclude=set(metric_columns))
        if any(stored[key] != value for key, value in scalars.items()):
            raise ValueError("Report run does not match stored evidence")
        if run.input_tokens is None or run.input_tokens > payload.config.input_token_budget:
            raise ValueError("Report input exceeds configured budget")
        for field, column in metric_columns.items():
            metric = getattr(run, field)
            if (
                stored[column] != metric.value
                or stored[column + "_reason"] != metric.unavailable_reason
            ):
                raise ValueError("Report measurement does not match stored evidence")
        job_ids.add(stored["job_id"])
    if len(job_ids) != 1:
        raise ValueError("Report must use one job")
    job = (
        connection.execute(sa.select(Job.__table__).where(Job.id == next(iter(job_ids))))
        .mappings()
        .one()
    )
    if job["phase"] != "completed" or job["attempt"] != payload.runs[0].attempt:
        raise ValueError("Report requires a completed matching job attempt")


@sa.event.listens_for(PublishedReport, "after_insert")
def link_report_runs(
    mapper: Mapper[PublishedReport], connection: Connection, report: PublishedReport
) -> None:
    payload = ReportContract.model_validate(report.payload)
    connection.execute(
        sa.insert(published_report_runs),
        [
            {"report_id": report.id, "run_id": run.id, "experiment_id": report.experiment_id}
            for run in payload.runs
        ],
    )


@sa.event.listens_for(PublishedReport, "before_update")
def immutable_report(
    mapper: Mapper[PublishedReport], connection: Connection, report: PublishedReport
) -> None:
    raise ValueError("Stored report snapshots are immutable; create a new report version")


@sa.event.listens_for(RunMetric, "before_update")
@sa.event.listens_for(Experiment, "before_update")
def immutable_published_evidence(
    mapper: Mapper[Any], connection: Connection, record: RunMetric | Experiment
) -> None:
    if isinstance(record, RunMetric):
        referenced = sa.exists().where(published_report_runs.c.run_id == record.id)
    else:
        referenced = sa.exists().where(PublishedReport.experiment_id == record.id)
    if connection.scalar(sa.select(referenced)):
        raise ValueError("Published evidence is immutable; create a new experiment/run version")
