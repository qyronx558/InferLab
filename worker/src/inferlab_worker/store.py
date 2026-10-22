"""Fenced queue transactions; no network calls or benchmark calculations."""

import hashlib
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from inferlab_api.contracts import (
    ExperimentSubmitRequest,
    JobPhase,
    RunMetrics,
    validate_submission,
)
from inferlab_api.database.coordination import database_now, lock_admission
from inferlab_api.database.models import (
    APIRequest,
    AuditEvent,
    Experiment,
    ExperimentMetadata,
    Job,
    JobAttempt,
    ModelRegistry,
    RunMetric,
    WorkerControl,
)
from inferlab_api.http_contracts import ExperimentResource
from inferlab_api.lifecycle import check_transition
from inferlab_api.resources import to_config

from .contracts import (
    CompletionConflict,
    ExecutionIdentity,
    Heartbeat,
    Lease,
    LeaseLost,
    RunBatch,
    WorkerPolicy,
)

LEASE_SECONDS = 120
HEARTBEAT_SECONDS = 30
RETRY_DELAY_SECONDS = 30
TRANSIENT = frozenset({"worker_lost", "engine_unavailable"})


def worker_audit(
    session: Session, action: str, job: Job, now: datetime, error: str | None = None
) -> None:
    session.add(
        AuditEvent(
            id="AUD-" + secrets.token_hex(16),
            recorded_at=now,
            actor="worker",
            action=action,
            outcome="failure" if error else "success",
            subject_type="job",
            subject_id=job.id,
            reason_code=error,
        )
    )


class WorkerStore:
    def __init__(
        self,
        sessions: sessionmaker[Session],
        policy: WorkerPolicy,
        now: Callable[[Session], datetime] = database_now,
    ) -> None:
        self.sessions = sessions
        self.policy = policy.model_copy(deep=True)
        self.now = now

    def _lock(self, session: Session) -> tuple[WorkerControl, datetime]:
        lock_admission(session)
        control = session.get(WorkerControl, 1, populate_existing=True)
        if control is None:
            raise RuntimeError("Apply worker migrations first")
        return control, self.now(session)

    def _authorized(self, session: Session, job: Job) -> Experiment:
        experiment = session.get(Experiment, job.experiment_id)
        if experiment is None:
            raise ValueError("Missing experiment")
        config = to_config(experiment)  # Revalidate every bound from persisted evidence.
        receipt = session.get(APIRequest, job.idempotency_key)
        if (
            receipt is None
            or receipt.status_code != 202
            or receipt.request_sha256 != job.request_sha256
        ):
            raise ValueError("No authorized admission receipt")
        original = ExperimentResource.model_validate(receipt.response)
        if (
            original.id != job.experiment_id
            or original.job.id != job.id
            or original.config != config
            or original.job.phase != "queued"
        ):
            raise ValueError("Admission receipt does not match")
        metadata = session.get(ExperimentMetadata, experiment.id)
        if metadata is not None and metadata.archived_at is not None:
            raise ValueError("Archived experiment")
        policy = self.policy
        validate_submission(
            ExperimentSubmitRequest(
                name=original.name,
                idempotency_key=job.idempotency_key,
                config=config,
            ),
            policy.registry,
        )
        model = session.get(ModelRegistry, config.model_id)
        if (
            model is None
            or any(
                getattr(model, field) != getattr(config, target)
                for field, target in (
                    ("revision", "model_revision"),
                    ("sha256", "model_sha256"),
                    ("quantization", "quantization"),
                )
            )
            or config.context_tokens > model.max_context_tokens
        ):
            raise ValueError("Stored model pin mismatch")
        workload = next(w for w in policy.registry.workloads if w.id == config.workload_id)
        if (
            workload.sha256 != experiment.workload_sha256
            or config.gpu_device_id != policy.gpu_device_id
            or config.max_output_tokens > policy.max_output_tokens
            or config.timeout_seconds > policy.max_runtime_seconds
            or (config.gpu_layers is not None and config.gpu_layers > policy.max_gpu_layers)
        ):
            raise ValueError("Operator policy mismatch")
        return experiment

    def _presence(self, control: WorkerControl, worker_id: str, now: datetime) -> None:
        control.worker_id = worker_id
        control.last_heartbeat_at = now

    def presence(self, worker_id: str) -> bool:
        with self.sessions() as session:
            control, now = self._lock(session)
            self._presence(control, worker_id, now)
            paused = control.paused
            session.commit()
            return paused

    def pause(self) -> None:
        with self.sessions() as session:
            control, _ = self._lock(session)
            control.paused = True
            control.pause_reason = "stop_unconfirmed"
            session.commit()

    def resume(self, *, stopped: bool) -> None:
        if not stopped:
            self.pause()
            return
        with self.sessions() as session:
            control, _ = self._lock(session)
            control.paused = False
            control.pause_reason = None
            session.commit()

    def claim(self, worker_id: str) -> Lease | None:
        with self.sessions() as session:
            control, now = self._lock(session)
            self._presence(control, worker_id, now)
            active = session.scalar(sa.select(sa.exists().where(Job.active_slot == 1)))
            if control.paused or active:
                session.commit()
                return None
            candidates = session.scalars(
                sa.select(Job)
                .where(Job.phase == "queued")
                .order_by(Job.created_at, Job.id)
                .limit(10)
            ).all()
            for job in candidates:
                # SQLite lease time has millisecond resolution; API admission
                # timestamps may have microseconds on the same clock tick.
                now = max(now, job.created_at)
                previous = session.get(JobAttempt, (job.id, job.attempt)) if job.attempt else None
                if (
                    previous is not None
                    and previous.retry_after_at is not None
                    and previous.retry_after_at > now
                ):
                    continue
                invalid = job.attempt >= 2 or (
                    job.attempt > 0
                    and (
                        previous is None
                        or previous.phase != "failed"
                        or previous.retry_after_at is None
                    )
                )
                try:
                    if invalid:
                        raise ValueError("Invalid retry state")
                    experiment = self._authorized(session, job)
                except ValueError:
                    self._reject(session, control, job, worker_id, now)
                    continue
                deadline = (
                    previous.deadline_at
                    if previous
                    else now + timedelta(seconds=experiment.timeout_seconds)
                )
                if deadline <= now:
                    job.phase, job.error_code, job.finished_at = "failed", "timeout", now
                    worker_audit(session, "fail", job, now, "timeout")
                    continue
                control.fencing_counter += 1
                job.attempt += 1
                job.phase, job.worker_id = "leased", worker_id
                job.fencing_token = control.fencing_counter
                job.active_slot = 1
                job.lease_expires_at = min(now + timedelta(seconds=LEASE_SECONDS), deadline)
                job.started_at = job.finished_at = None
                job.error_code = None
                session.add(
                    JobAttempt(
                        job_id=job.id,
                        number=job.attempt,
                        fencing_token=control.fencing_counter,
                        worker_id=worker_id,
                        phase="leased",
                        leased_at=now,
                        deadline_at=deadline,
                        last_heartbeat_at=now,
                    )
                )
                worker_audit(session, "claim", job, now)
                lease = Lease(
                    job.id,
                    worker_id,
                    job.attempt,
                    control.fencing_counter,
                    to_config(experiment),
                    deadline,
                    min(experiment.timeout_seconds, (deadline - now).total_seconds()),
                    ExecutionIdentity(
                        device_name=experiment.device_name,
                        driver_version=experiment.driver_version,
                        workload_sha256=experiment.workload_sha256,
                        methodology_version=experiment.methodology_version,
                    ),
                    job.lease_expires_at,
                )
                session.commit()
                return lease
            session.commit()
            return None

    def _reject(
        self, session: Session, control: WorkerControl, job: Job, worker_id: str, now: datetime
    ) -> None:
        # Invalid/unreceipted records never reach a runner, but retain failure evidence.
        job.phase, job.error_code = "failed", "validation_error"
        job.finished_at = max(now, job.created_at)
        if job.attempt == 0:
            job.attempt = 1
            control.fencing_counter += 1
            job.fencing_token = control.fencing_counter
            session.add(
                JobAttempt(
                    job_id=job.id,
                    number=1,
                    fencing_token=control.fencing_counter,
                    worker_id=worker_id,
                    phase="failed",
                    leased_at=now,
                    finished_at=now,
                    deadline_at=now,
                    last_heartbeat_at=now,
                    error_code="validation_error",
                )
            )
        worker_audit(session, "fail", job, now, "validation_error")

    def _owned(
        self, session: Session, lease: Lease, now: datetime, *, fresh: bool = True
    ) -> tuple[Job, JobAttempt]:
        job = session.get(Job, lease.job_id)
        attempt = session.get(JobAttempt, (lease.job_id, lease.attempt))
        if (
            job is None
            or attempt is None
            or job.worker_id != lease.worker_id
            or job.attempt != lease.attempt
            or job.fencing_token != lease.token
            or attempt.fencing_token != lease.token
            or attempt.worker_id != lease.worker_id
            or job.phase not in {"leased", "running"}
            or (
                fresh
                and (
                    job.lease_expires_at is None
                    or job.lease_expires_at <= now
                    or attempt.deadline_at <= now
                )
            )
        ):
            raise LeaseLost("Stale or expired execution")
        return job, attempt

    def start(self, lease: Lease) -> None:
        with self.sessions() as session:
            control, now = self._lock(session)
            job, attempt = self._owned(session, lease, now)
            if control.paused or job.cancellation_requested or job.phase != "leased":
                raise LeaseLost("Execution is not startable")
            # Revalidate immediately before dispatch, in case an operator revoked policy data.
            self._authorized(session, job)
            job.phase = attempt.phase = "running"
            job.started_at = attempt.started_at = max(now, job.created_at, attempt.leased_at)
            worker_audit(session, "start", job, now)
            session.commit()

    def heartbeat(self, lease: Lease) -> Heartbeat:
        with self.sessions() as session:
            control, now = self._lock(session)
            job, attempt = self._owned(session, lease, now)
            job.lease_expires_at = min(now + timedelta(seconds=LEASE_SECONDS), attempt.deadline_at)
            attempt.last_heartbeat_at = now
            self._presence(control, lease.worker_id, now)
            cancelled = job.cancellation_requested or control.paused
            session.commit()
            return Heartbeat(cancelled, job.lease_expires_at)

    def status(self, lease: Lease) -> bool:
        with self.sessions() as session:
            now = self.now(session)
            job, _ = self._owned(session, lease, now)
            control = session.get(WorkerControl, 1)
            return job.cancellation_requested or control is None or control.paused

    def _end(
        self,
        session: Session,
        control: WorkerControl,
        job: Job,
        attempt: JobAttempt,
        now: datetime,
        error: str,
        stopped: bool,
    ) -> None:
        if not stopped:
            control.paused, control.pause_reason = True, "stop_unconfirmed"
            error = "worker_lost"
        elif job.cancellation_requested:
            error = "cancelled"
        elif now >= attempt.deadline_at:
            error = "timeout"
        attempt.phase = "cancelled" if error == "cancelled" else "failed"
        attempt.error_code, attempt.finished_at = (
            error,
            max(now, attempt.started_at or attempt.leased_at),
        )
        job.active_slot = job.lease_expires_at = None
        retry = (
            stopped
            and not control.paused
            and error in TRANSIENT
            and job.attempt < 2
            and now + timedelta(seconds=RETRY_DELAY_SECONDS) < attempt.deadline_at
        )
        if retry:
            # Phase/active-slot are a coupled update. Do not flush the interim
            # state while checking capacity; the admission lock already fences it.
            with session.no_autoflush:
                pending = session.scalar(
                    sa.select(sa.func.count()).select_from(Job).where(Job.phase == "queued")
                )
            retry = (pending or 0) < 10
        if retry:
            check_transition(cast(JobPhase, job.phase), "queued", retry_authorized=True)
            attempt.retry_after_at = now + timedelta(seconds=RETRY_DELAY_SECONDS)
            job.phase = "queued"
            job.started_at = job.finished_at = job.error_code = None
        else:
            job.phase = attempt.phase
            job.error_code, job.finished_at = error, attempt.finished_at
        worker_audit(session, "fail", job, now, error)

    def abort(self, lease: Lease, error: str, *, stopped: bool) -> None:
        with self.sessions() as session:
            control, now = self._lock(session)
            job, attempt = self._owned(session, lease, now, fresh=False)
            self._end(session, control, job, attempt, now, error, stopped)
            session.commit()

    def reconcile(self, *, stopped: bool) -> int:
        with self.sessions() as session:
            control, now = self._lock(session)
            if not stopped:
                control.paused, control.pause_reason = True, "stop_unconfirmed"
            jobs = session.scalars(
                sa.select(Job).where(
                    Job.active_slot == 1,
                    Job.lease_expires_at <= now,
                )
            ).all()
            for job in jobs:
                attempt = session.get(JobAttempt, (job.id, job.attempt))
                if attempt is None:  # Recovery of pre-worker migration leases.
                    leased_at = job.started_at or job.created_at
                    experiment = session.get(Experiment, job.experiment_id)
                    budget = min(
                        experiment.timeout_seconds
                        if experiment
                        else self.policy.max_runtime_seconds,
                        self.policy.max_runtime_seconds,
                    )
                    attempt = JobAttempt(
                        job_id=job.id,
                        number=job.attempt,
                        fencing_token=cast(int, job.fencing_token),
                        worker_id=cast(str, job.worker_id),
                        phase=job.phase,
                        leased_at=leased_at,
                        started_at=job.started_at,
                        deadline_at=leased_at + timedelta(seconds=budget),
                        last_heartbeat_at=leased_at,
                    )
                    session.add(attempt)
                    control.fencing_counter = max(
                        control.fencing_counter, cast(int, job.fencing_token)
                    )
                self._end(session, control, job, attempt, now, "worker_lost", stopped)
                worker_audit(session, "recover", job, now, "worker_lost")
            session.commit()
            return len(jobs)

    def complete(self, lease: Lease, batch: RunBatch) -> bool:
        batch = RunBatch.model_validate(batch.model_dump())
        runs = self._validated_runs(lease, batch)
        digest = hashlib.sha256(
            json.dumps(
                [run.model_dump(mode="json") for run in runs],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        with self.sessions() as session:
            control, now = self._lock(session)
            previous = session.get(JobAttempt, (lease.job_id, lease.attempt))
            if (
                previous is not None
                and previous.phase == "completed"
                and previous.fencing_token == lease.token
                and previous.worker_id == lease.worker_id
            ):
                if previous.result_sha256 != digest:
                    raise CompletionConflict("Completion differs from accepted evidence")
                return False
            job, attempt = self._owned(session, lease, now)
            if job.phase != "running" or job.cancellation_requested or control.paused:
                raise LeaseLost("Cancellation or missing start prevents completion")
            if any(
                run.recorded_at < attempt.leased_at or run.recorded_at > now + timedelta(seconds=5)
                for run in runs
            ):
                raise ValueError("Run timestamps are outside this attempt")
            for run in runs:
                values = run.model_dump(
                    exclude={"ttft", "request_latency", "decode_throughput", "peak_vram", "quality"}
                )
                for field, column in {
                    "ttft": "ttft_ms",
                    "request_latency": "request_latency_ms",
                    "decode_throughput": "decode_tokens_per_second",
                    "peak_vram": "peak_vram_mib",
                    "quality": "quality_score",
                }.items():
                    metric = getattr(run, field)
                    values[column], values[column + "_reason"] = (
                        metric.value,
                        metric.unavailable_reason,
                    )
                session.add(RunMetric(**values, job_id=job.id))
            job.phase = attempt.phase = "completed"
            job.finished_at = attempt.finished_at = max(
                now, attempt.started_at or attempt.leased_at
            )
            job.active_slot = job.lease_expires_at = None
            attempt.result_sha256 = digest
            worker_audit(session, "complete", job, now)
            session.commit()
            return True

    def _validated_runs(self, lease: Lease, batch: RunBatch) -> list[RunMetrics]:
        config = lease.config
        expected = {("warmup", i) for i in range(config.warmups)} | {
            ("measured", i) for i in range(config.repetitions)
        }
        actual = {(run.kind, run.repetition) for run in batch.runs}
        if actual != expected or len(actual) != len(batch.runs):
            raise ValueError("Incomplete or duplicated run batch")
        runs = []
        for run in batch.runs:
            if (
                run.experiment_id != config.experiment_id
                or run.attempt != lease.attempt
                or run.condition != config.condition
                or run.state != "complete"
                or run.input_tokens is None
                or run.input_tokens > config.input_token_budget
                or run.output_tokens is None
                or run.output_tokens > config.max_output_tokens
            ):
                raise ValueError("Run exceeds bounds or does not match this attempt")
            key = f"{lease.job_id}:{lease.token}:{run.kind}:{run.repetition}"
            runs.append(
                run.model_copy(
                    update={
                        "id": "RUN-" + hashlib.sha256(key.encode()).hexdigest()[:32],
                        "recorded_at": run.recorded_at.astimezone(UTC),
                    }
                )
            )
        return sorted(runs, key=lambda run: (run.kind, run.repetition))
