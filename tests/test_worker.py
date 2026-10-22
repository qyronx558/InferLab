"""DEMO DATA only: failure/restart simulations and real CPU child-process isolation."""

import copy
import json
import multiprocessing
import os
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from typing import Any, cast

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from inferlab_api.contracts import ExperimentConfig, Provenance, Registry, RunMetrics
from inferlab_api.database.models import (
    APIRequest,
    AuditEvent,
    Job,
    JobAttempt,
    RunMetric,
    WorkerControl,
)
from inferlab_api.database.session import create_database_engine, session_factory
from inferlab_api.dependencies import Settings
from inferlab_api.main import create_app
from inferlab_worker.contracts import (
    Cancellation,
    CompletionConflict,
    ExecutionIdentity,
    Lease,
    LeaseLost,
    RunBatch,
    RunnerFailure,
    WorkerPolicy,
)
from inferlab_worker.locking import GPULock, WorkerAlreadyRunning
from inferlab_worker.processes import ProcessBackend
from inferlab_worker.service import Worker
from inferlab_worker.store import WorkerStore

ROOT = Path(__file__).resolve().parents[1]
DEMO: dict[str, Any] = json.loads((ROOT / "contracts/fixtures/demo.json").read_text("utf-8"))
ORIGIN = "https://127.0.0.1:5173"


class Clock:
    def __init__(self) -> None:
        self.value = datetime.now(UTC)
        self.elapsed = 0.0

    def now(self) -> datetime:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += timedelta(seconds=seconds)
        self.elapsed += seconds


class Admission:
    def registry(self) -> Registry:
        return Registry.model_validate(DEMO["registry"]["data"])

    def resolve(self, config: ExperimentConfig) -> Provenance:
        value = copy.deepcopy(DEMO["experiments"]["data"]["items"][0]["provenance"])
        value["hardware"]["gpu_layers"] = config.gpu_layers
        return Provenance.model_validate(value)


@dataclass
class Harness:
    engine: Engine
    client: TestClient
    headers: dict[str, str]
    clock: Clock
    store: WorkerStore
    lock: Path

    def queue(self, identifier: str = "EXP-worker", **overrides: object) -> str:
        config = copy.deepcopy(DEMO["experiments"]["data"]["items"][0]["config"])
        config.update(experiment_id=identifier, warmups=0, repetitions=1)
        config.update(overrides)
        response = self.client.post(
            "/api/v1/experiments",
            json={
                "name": "DEMO DATA worker tests",
                "idempotency_key": identifier,
                "config": config,
            },
            headers=self.headers | {"Idempotency-Key": identifier},
        )
        assert response.status_code == 202, response.text
        return cast(str, response.json()["job"]["id"])

    def claim(self, *, start: bool = True) -> Lease:
        lease = self.store.claim("worker-a")
        assert lease is not None
        if start:
            self.store.start(lease)
        return lease

    def cancel(self, identifier: str = "EXP-worker") -> int:
        response = self.client.post(
            f"/api/v1/experiments/{identifier}/cancel",
            headers=self.headers
            | {
                "Idempotency-Key": "cancel-" + identifier,
            },
        )
        return response.status_code


@pytest.fixture(scope="session")
def worker_password_hash() -> str:
    return PasswordHasher().hash("worker-tests-only-not-a-production-password")


@pytest.fixture
def worker(tmp_path: Path, worker_password_hash: str) -> Iterator[Harness]:
    url = "sqlite:///" + (tmp_path / "worker.db").as_posix()
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    clock = Clock()
    policy = WorkerPolicy(registry=Admission().registry(), gpu_device_id="gpu-0")
    store = WorkerStore(session_factory(engine), policy, now=lambda _: clock.now())
    app = create_app(
        engine=engine,
        settings=Settings(ORIGIN, worker_password_hash),
        runner=Admission(),
        clock=clock.now,
    )
    try:
        with TestClient(app, base_url="https://127.0.0.1") as client:
            login = client.post(
                "/api/v1/auth/login",
                json={"password": "worker-tests-only-not-a-production-password"},
                headers={"Origin": ORIGIN},
            )
            assert login.status_code == 200
            yield Harness(
                engine,
                client,
                {"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]},
                clock,
                store,
                tmp_path / "gpu.lock",
            )
    finally:
        engine.dispose()


def synthetic_batch(config: ExperimentConfig, attempt: int, now: datetime) -> RunBatch:
    """Fixture construction, not benchmark execution or metric calculations."""
    runs = []
    for kind, count in (("warmup", config.warmups), ("measured", config.repetitions)):
        for repetition in range(count):
            runs.append(
                RunMetrics.model_validate(
                    {
                        "id": "DEMO-run",
                        "experiment_id": config.experiment_id,
                        "attempt": attempt,
                        "state": "complete",
                        "condition": config.condition,
                        "kind": kind,
                        "repetition": repetition,
                        "recorded_at": now,
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "error_code": None,
                        "ttft": {"value": None, "unavailable_reason": "not_measured", "unit": "ms"},
                        "request_latency": {
                            "value": None,
                            "unavailable_reason": "not_measured",
                            "unit": "ms",
                        },
                        "decode_throughput": {
                            "value": None,
                            "unavailable_reason": "not_measured",
                            "unit": "tok/s",
                        },
                        "peak_vram": {
                            "value": None,
                            "unavailable_reason": "not_measured",
                            "unit": "MiB",
                        },
                        "quality": {
                            "value": None,
                            "unavailable_reason": "not_measured",
                            "unit": "score",
                        },
                    }
                )
            )
    return RunBatch(runs=runs)


def batch_for(worker: Harness, lease: Lease) -> RunBatch:
    return synthetic_batch(lease.config, lease.attempt, worker.clock.now())


def job_state(worker: Harness, job_id: str) -> tuple[str, str | None]:
    with Session(worker.engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        return job.phase, job.error_code


def test_atomic_single_slot_claim_across_workers(worker: Harness) -> None:
    worker.queue("EXP-a")
    worker.queue("EXP-b")
    barrier = Barrier(2)

    def claim(identifier: str) -> Lease | None:
        barrier.wait(timeout=10)
        return worker.store.claim(identifier)

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = list(executor.map(claim, ("worker-a", "worker-b")))
    assert sum(lease is not None for lease in leases) == 1
    with Session(worker.engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(Job).where(Job.active_slot == 1))
            == 1
        )
        assert session.scalar(sa.select(sa.func.count()).select_from(JobAttempt)) == 1


def test_heartbeat_renews_only_current_unexpired_fence(worker: Harness) -> None:
    worker.queue()
    lease = worker.claim()
    worker.clock.advance(30)
    assert worker.store.heartbeat(lease).cancelled is False
    with Session(worker.engine) as session:
        job = session.get(Job, lease.job_id)
        control = session.get(WorkerControl, 1)
        assert job is not None and job.lease_expires_at == worker.clock.now() + timedelta(
            seconds=120
        )
        assert control is not None and control.last_heartbeat_at == worker.clock.now()
    with pytest.raises(LeaseLost):
        worker.store.heartbeat(replace(lease, token=lease.token + 1))
    worker.clock.advance(121)
    with pytest.raises(LeaseLost):
        worker.store.heartbeat(lease)


def test_shutdown_recovery_retains_attempt_and_fences_stale_results(worker: Harness) -> None:
    job_id = worker.queue()
    old = worker.claim()
    old_batch = batch_for(worker, old)
    worker.clock.advance(121)
    restarted = WorkerStore(
        session_factory(worker.engine), worker.store.policy, now=lambda _: worker.clock.now()
    )
    assert restarted.reconcile(stopped=True) == 1
    assert job_state(worker, job_id) == ("queued", None)
    assert restarted.claim("worker-restarted") is None  # Backoff is durable.
    with pytest.raises(LeaseLost):
        restarted.complete(old, old_batch)
    worker.clock.advance(30)
    new = restarted.claim("worker-restarted")
    assert new is not None and new.attempt == 2 and new.token > old.token
    assert new.deadline_at == old.deadline_at  # Retry does not reset the job budget.
    restarted.start(new)
    assert restarted.complete(new, batch_for(worker, new)) is True
    with Session(worker.engine) as session:
        previous = session.get(JobAttempt, (job_id, 1))
        assert (
            previous is not None
            and previous.phase == "failed"
            and previous.error_code == "worker_lost"
        )
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 1


@pytest.mark.parametrize(
    "error,retries",
    [
        ("engine_unavailable", True),
        ("worker_lost", True),
        ("out_of_memory", False),
        ("validation_error", False),
        ("timeout", False),
    ],
)
def test_retry_allowlist_and_two_attempt_limit(worker: Harness, error: str, retries: bool) -> None:
    job_id = worker.queue()
    lease = worker.claim()
    worker.store.abort(lease, error, stopped=True)
    assert job_state(worker, job_id)[0] == ("queued" if retries else "failed")
    worker.clock.advance(30)
    second = worker.store.claim("worker-a")
    if not retries:
        assert second is None
        return
    assert second is not None and second.attempt == 2
    worker.store.start(second)
    worker.store.abort(second, error, stopped=True)
    worker.clock.advance(31)
    assert worker.store.claim("worker-a") is None
    assert job_state(worker, job_id) == ("failed", error)


def test_uncertain_stop_persists_pause_and_requires_explicit_resume(worker: Harness) -> None:
    job_id = worker.queue()
    lease = worker.claim()
    worker.clock.advance(121)
    assert worker.store.reconcile(stopped=False) == 1
    assert job_state(worker, job_id) == ("failed", "worker_lost")
    worker.queue("EXP-other")
    restarted = WorkerStore(
        session_factory(worker.engine), worker.store.policy, now=lambda _: worker.clock.now()
    )
    assert restarted.claim("worker-new") is None
    restarted.resume(stopped=False)
    assert restarted.claim("worker-new") is None
    restarted.resume(stopped=True)
    assert restarted.claim("worker-new") is not None
    with pytest.raises(LeaseLost):
        restarted.complete(lease, batch_for(worker, lease))


def test_cancellation_wins_completion_and_is_acknowledged_only_after_stop(worker: Harness) -> None:
    job_id = worker.queue()
    lease = worker.claim()
    batch = batch_for(worker, lease)
    assert worker.cancel() == 200
    assert job_state(worker, job_id) == ("running", None)
    assert worker.store.status(lease) is True
    with pytest.raises(LeaseLost):
        worker.store.complete(lease, batch)
    worker.store.abort(lease, "cancelled", stopped=True)
    assert job_state(worker, job_id) == ("cancelled", "cancelled")
    with Session(worker.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 0


def test_idempotent_atomic_result_commit_and_conflicting_replay(worker: Harness) -> None:
    job_id = worker.queue(warmups=2, repetitions=2)
    lease = worker.claim()
    batch = batch_for(worker, lease)
    assert worker.store.complete(lease, batch) is True
    assert worker.store.complete(lease, RunBatch(runs=list(reversed(batch.runs)))) is False
    worker.clock.advance(1000)
    assert worker.store.complete(lease, batch) is False
    changed = batch.model_copy(deep=True)
    changed.runs[0].output_tokens = 2
    with pytest.raises(CompletionConflict):
        worker.store.complete(lease, changed)
    assert worker.cancel() == 409
    with Session(worker.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 4
        assert (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "complete")
            )
            == 1
        )
        attempt = session.get(JobAttempt, (job_id, 1))
        assert attempt is not None and attempt.result_sha256 is not None


@pytest.mark.parametrize(
    "mutation", ["partial", "duplicate", "output_overflow", "wrong_attempt", "wrong_experiment"]
)
def test_incomplete_or_invalid_batches_never_write_partial_success(
    worker: Harness, mutation: str
) -> None:
    job_id = worker.queue(warmups=1, repetitions=2)
    lease = worker.claim()
    batch = batch_for(worker, lease)
    if mutation == "partial":
        batch.runs.pop()
    elif mutation == "duplicate":
        batch.runs[-1] = batch.runs[0].model_copy()
    elif mutation == "output_overflow":
        batch.runs[0].output_tokens = lease.config.max_output_tokens + 1
    elif mutation == "wrong_attempt":
        batch.runs[0].attempt = 2
    else:
        batch.runs[0].experiment_id = "EXP-other"
    with pytest.raises(ValueError):
        worker.store.complete(lease, batch)
    assert job_state(worker, job_id)[0] == "running"
    with Session(worker.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 0


@pytest.mark.parametrize(
    "change", ["unreceipted", "tampered", "model_revoked", "token_cap", "time_cap", "gpu_device"]
)
def test_only_receipted_fixed_allowlist_jobs_execute(worker: Harness, change: str) -> None:
    job_id = worker.queue()
    policy = worker.store.policy.model_copy(deep=True)
    with Session(worker.engine) as session:
        if change == "unreceipted":
            receipt = session.get(APIRequest, "EXP-worker")
            assert receipt is not None
            session.delete(receipt)
        elif change == "tampered":
            session.execute(sa.update(Job).where(Job.id == job_id).values(request_sha256="f" * 64))
        session.commit()
    if change == "model_revoked":
        policy.registry.models = []
    elif change == "token_cap":
        policy.max_output_tokens = 128
    elif change == "time_cap":
        policy.max_runtime_seconds = 120
    elif change == "gpu_device":
        policy.gpu_device_id = "gpu-other"
    store = WorkerStore(session_factory(worker.engine), policy, now=lambda _: worker.clock.now())
    assert store.claim("worker-a") is None
    assert job_state(worker, job_id) == ("failed", "validation_error")


def test_job_budget_includes_retry_and_suspended_time(worker: Harness) -> None:
    job_id = worker.queue(timeout_seconds=60)
    lease = worker.claim()
    worker.clock.advance(61)
    with pytest.raises(LeaseLost):
        worker.store.complete(lease, batch_for(worker, lease))
    assert worker.store.reconcile(stopped=True) == 1
    assert job_state(worker, job_id) == ("failed", "timeout")
    assert worker.store.claim("worker-a") is None


class FakeExecution:
    def __init__(self, harness: Harness, lease: Lease, mode: str) -> None:
        self.harness, self.lease, self.mode = harness, lease, mode
        self.closed = False

    def poll(self) -> RunBatch | None:
        if self.mode == "complete":
            return batch_for(self.harness, self.lease)
        if self.mode == "partial":
            batch = batch_for(self.harness, self.lease)
            batch.runs = []
            return batch
        if self.mode == "failure":
            raise RunnerFailure("out_of_memory")
        return None

    def close(self) -> bool:
        self.closed = True
        return True

    def renew(self, expires_at: datetime) -> None:
        pass


class FakeBackend:
    def __init__(self, harness: Harness, mode: str = "complete", confirmed: bool = True) -> None:
        self.harness, self.mode, self.confirmed = harness, mode, confirmed
        self.starts = 0
        self.execution: FakeExecution | None = None

    def start(
        self, lease: Lease, execution_lock: Path, deadline: float | None = None
    ) -> FakeExecution:
        self.starts += 1
        self.execution = FakeExecution(self.harness, lease, self.mode)
        return self.execution

    def stop_and_confirm(self, execution_lock: Path) -> bool:
        return self.confirmed


def supervisor(worker: Harness, backend: FakeBackend, *, wait: Any = None) -> Worker:
    def advance(stop: Event, seconds: float) -> bool:
        worker.clock.advance(seconds)
        return stop.is_set()

    return Worker(
        worker.store,
        backend,
        "worker-service",
        worker.lock,
        monotonic=lambda: worker.clock.elapsed,
        wait=wait or advance,
    )


@pytest.mark.parametrize(
    "mode,phase,error",
    [
        ("complete", "completed", None),
        ("partial", "failed", "validation_error"),
        ("failure", "failed", "out_of_memory"),
        ("hang", "failed", "timeout"),
    ],
)
def test_supervisor_enforces_completion_failure_and_runtime(
    worker: Harness, mode: str, phase: str, error: str | None
) -> None:
    job_id = worker.queue(timeout_seconds=35)
    backend = FakeBackend(worker, mode)
    supervisor(worker, backend).serve(Event(), once=True)
    assert job_state(worker, job_id) == (phase, error)
    assert backend.execution is not None and backend.execution.closed
    with Session(worker.engine) as session:
        count = session.scalar(sa.select(sa.func.count()).select_from(RunMetric))
        assert count == (1 if phase == "completed" else 0)


def test_supervisor_graceful_shutdown_does_not_accept_partial_output(worker: Harness) -> None:
    job_id = worker.queue()
    stop = Event()
    backend = FakeBackend(worker, "hang")

    def shutdown(event: Event, seconds: float) -> bool:
        worker.clock.advance(seconds)
        event.set()
        return True

    supervisor(worker, backend, wait=shutdown).serve(stop, once=True)
    assert job_state(worker, job_id) == ("queued", None)
    with Session(worker.engine) as session:
        attempt = session.get(JobAttempt, (job_id, 1))
        assert attempt is not None and attempt.error_code == "worker_lost"
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 0


def test_database_outage_after_execution_recovers_without_success(
    worker: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    job_id = worker.queue()
    backend = FakeBackend(worker)

    def unavailable(lease: Lease, batch: RunBatch) -> bool:
        raise OperationalError("storage unavailable", {}, RuntimeError("private-canary"))

    monkeypatch.setattr(worker.store, "complete", unavailable)
    with pytest.raises(OperationalError):
        supervisor(worker, backend).serve(Event(), once=True)
    assert job_state(worker, job_id) == ("running", None)
    assert backend.execution is not None and backend.execution.closed
    worker.clock.advance(121)
    restarted = WorkerStore(
        session_factory(worker.engine), worker.store.policy, now=lambda _: worker.clock.now()
    )
    assert restarted.reconcile(stopped=True) == 1
    with Session(worker.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 0


def test_persisted_pause_cannot_be_cleared_by_simple_restart(worker: Harness) -> None:
    worker.queue()
    worker.store.pause()
    backend = FakeBackend(worker)
    supervisor(worker, backend).serve(Event(), once=True)
    assert backend.starts == 0
    supervisor(worker, backend).serve(Event(), once=True, resume=True)
    assert backend.starts == 1


def test_os_gpu_lock_excludes_second_worker_and_releases_on_close(worker: Harness) -> None:
    with GPULock(worker.lock):
        with pytest.raises(WorkerAlreadyRunning), GPULock(worker.lock):
            pass
    with GPULock(worker.lock):
        assert worker.lock.exists()


class SyntheticPlugin:
    def verify_installation(self, config: ExperimentConfig, expected: ExecutionIdentity) -> bool:
        return True

    def run(self, config: ExperimentConfig, attempt: int, cancellation: Cancellation) -> RunBatch:
        return synthetic_batch(config, attempt, datetime.now(UTC))

    def stop_and_confirm(self) -> bool:
        return True


class HangingPlugin(SyntheticPlugin):
    def run(self, config: ExperimentConfig, attempt: int, cancellation: Cancellation) -> RunBatch:
        marker = os.environ.get("INFERLAB_TEST_CHILD_MARKER")
        if marker:
            Path(marker).touch()
        while True:
            time.sleep(0.02)


class BadInstallation(SyntheticPlugin):
    def verify_installation(self, config: ExperimentConfig, expected: ExecutionIdentity) -> bool:
        return False

    def run(self, config: ExperimentConfig, attempt: int, cancellation: Cancellation) -> RunBatch:
        raise AssertionError("Unapproved installation must never execute")


class CrashPlugin(SyntheticPlugin):
    def run(self, config: ExperimentConfig, attempt: int, cancellation: Cancellation) -> RunBatch:
        os._exit(7)  # Simulates abrupt child death without a completion receipt.


class HangingStop(SyntheticPlugin):
    def stop_and_confirm(self) -> bool:
        time.sleep(60)
        return True


def _hold_lock(path: str, marker: str) -> None:
    with GPULock(Path(path)):
        Path(marker).touch()
        time.sleep(60)


def wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 15
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert path.exists(), "CPU child did not initialize within the test deadline"


def test_os_lock_is_released_when_parent_is_killed(worker: Harness, tmp_path: Path) -> None:
    marker = tmp_path / "ready"
    process = multiprocessing.get_context("spawn").Process(
        target=_hold_lock, args=(str(worker.lock), str(marker))
    )
    process.start()
    try:
        wait_for_file(marker)
        with pytest.raises(WorkerAlreadyRunning), GPULock(worker.lock):
            pass
    finally:
        process.terminate()
        process.join(timeout=5)
        assert not process.is_alive()
        process.close()
    with GPULock(worker.lock):
        assert worker.lock.exists()


def test_uncooperative_child_is_killed_with_bounded_grace(
    worker: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker.queue()
    lease = worker.claim()
    marker = tmp_path / "child-ready"
    monkeypatch.setenv("INFERLAB_TEST_CHILD_MARKER", str(marker))
    backend = ProcessBackend("test_worker:HangingPlugin", grace_seconds=0.05)
    execution = backend.start(lease, worker.lock.with_suffix(".execution"))
    try:
        wait_for_file(marker)
        start = time.monotonic()
        assert execution.close() is True
        assert time.monotonic() - start < 3
        assert execution.closed
    finally:
        execution.close()
    assert backend.stop_and_confirm(worker.lock.with_suffix(".execution")) is True


@pytest.mark.parametrize(
    "factory,error", [("BadInstallation", "validation_error"), ("CrashPlugin", "worker_lost")]
)
def test_spawned_child_verification_and_crash(worker: Harness, factory: str, error: str) -> None:
    worker.queue()
    execution = ProcessBackend("test_worker:" + factory).start(
        worker.claim(), worker.lock.with_suffix(".execution")
    )
    try:
        deadline = time.monotonic() + 15
        with pytest.raises(RunnerFailure) as failure:
            while time.monotonic() < deadline:
                execution.poll()
                time.sleep(0.02)
        assert failure.value.code == error
    finally:
        execution.close()


def test_stop_probe_has_a_hard_timeout_and_pauses(worker: Harness) -> None:
    job_id = worker.queue()
    backend = ProcessBackend("test_worker:HangingStop", probe_seconds=0.1)
    Worker(worker.store, backend, "worker-probe", worker.lock).serve(Event(), once=True)
    assert job_state(worker, job_id) == ("queued", None)
    with Session(worker.engine) as session:
        control = session.get(WorkerControl, 1)
        assert control is not None and control.paused and control.pause_reason == "stop_unconfirmed"


@pytest.mark.parametrize(
    "factory,timeout,phase,error",
    [
        ("SyntheticPlugin", 60, "completed", None),
        ("HangingPlugin", 1, "failed", "timeout"),
    ],
)
def test_real_spawn_supervisor_with_database_clock(
    worker: Harness,
    factory: str,
    timeout: int,
    phase: str,
    error: str | None,
) -> None:
    worker.clock.value = datetime.now(UTC)
    job_id = worker.queue(timeout_seconds=timeout)
    store = WorkerStore(session_factory(worker.engine), worker.store.policy)
    backend = ProcessBackend("test_worker:" + factory, grace_seconds=0.05)
    Worker(store, backend, "worker-real-process", worker.lock).serve(Event(), once=True)
    assert job_state(worker, job_id) == (phase, error)
    with Session(worker.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == (
            1 if phase == "completed" else 0
        )


def _launch_orphan(lock: str, lease: Lease, marker: str) -> None:
    os.environ["INFERLAB_TEST_CHILD_MARKER"] = marker
    with GPULock(Path(lock)):
        backend = ProcessBackend("test_worker:HangingPlugin")
        # Keep a reference until os._exit, bypassing normal multiprocessing cleanup.
        execution = backend.start(lease, Path(lock + ".execution"))
        wait_for_file(Path(marker))
        assert execution.process.is_alive()
        os._exit(17)


def test_orphan_runner_exits_before_a_restarted_worker_can_dispatch(
    worker: Harness, tmp_path: Path
) -> None:
    worker.queue()
    lease = worker.claim()
    marker = tmp_path / "orphan-ready"
    parent = multiprocessing.get_context("spawn").Process(
        target=_launch_orphan,
        args=(str(worker.lock), lease, str(marker)),
    )
    parent.start()
    try:
        wait_for_file(marker)
        parent.join(timeout=10)
        assert parent.exitcode == 17
        execution_lock = Path(str(worker.lock) + ".execution")
        deadline = time.monotonic() + 5
        acquired = False
        while time.monotonic() < deadline:
            try:
                with GPULock(execution_lock):
                    acquired = True
                    break
            except WorkerAlreadyRunning:
                time.sleep(0.02)
        assert acquired, "Orphan did not release its execution lock after supervisor death"
        with GPULock(worker.lock):
            assert ProcessBackend("test_worker:SyntheticPlugin").stop_and_confirm(execution_lock)
    finally:
        if parent.is_alive():
            parent.terminate()
            parent.join(timeout=5)
        parent.close()


def test_result_constraint_failure_rolls_back_entire_batch(worker: Harness) -> None:
    job_id = worker.queue(repetitions=2)
    lease = worker.claim()
    batch = batch_for(worker, lease)
    batch.runs[-1].ttft.value = 2.0
    batch.runs[-1].ttft.unavailable_reason = None
    batch.runs[-1].request_latency.value = 1.0
    batch.runs[-1].request_latency.unavailable_reason = None
    with pytest.raises(IntegrityError):
        worker.store.complete(lease, batch)
    assert job_state(worker, job_id) == ("running", None)
    with Session(worker.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 0
        attempt = session.get(JobAttempt, (job_id, 1))
        assert attempt is not None and attempt.result_sha256 is None


def test_lost_commit_ack_replays_without_duplicate_results(worker: Harness) -> None:
    worker.queue()
    lease = worker.claim()
    batch = batch_for(worker, lease)
    worker.store.complete(lease, batch)
    # Simulate loss of the caller's acknowledgement and a fresh worker/store.
    restarted = WorkerStore(
        session_factory(worker.engine), worker.store.policy, now=lambda _: worker.clock.now()
    )
    assert restarted.complete(lease, batch) is False
    assert restarted.reconcile(stopped=True) == 0
    with Session(worker.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 1


def test_stop_failure_after_finished_child_pauses_and_discards_results(worker: Harness) -> None:
    job_id = worker.queue()

    class LosesConfirmation(FakeBackend):
        calls = 0

        def stop_and_confirm(self, execution_lock: Path) -> bool:
            self.calls += 1
            return self.calls == 1  # Startup verified; post-run engine stop cannot be proved.

    backend = LosesConfirmation(worker)
    supervisor(worker, backend).serve(Event(), once=True)
    assert job_state(worker, job_id) == ("failed", "worker_lost")
    with Session(worker.engine) as session:
        control = session.get(WorkerControl, 1)
        assert control is not None and control.paused
        assert session.scalar(sa.select(sa.func.count()).select_from(RunMetric)) == 0


@pytest.mark.parametrize("expired_lease", [False, True])
def test_child_guard_stops_even_when_supervisor_does_not_poll_or_renew(
    worker: Harness, expired_lease: bool
) -> None:
    worker.queue()
    lease = worker.claim()
    if expired_lease:
        lease = replace(lease, expires_at=datetime.now(UTC) + timedelta(seconds=2))
    deadline = time.monotonic() + (30 if expired_lease else 1)
    execution = ProcessBackend("test_worker:HangingPlugin", grace_seconds=0.05).start(
        lease,
        worker.lock.with_suffix(".execution"),
        deadline,
    )
    try:
        execution.process.join(timeout=6)
        assert not execution.process.is_alive()
        with pytest.raises(RunnerFailure) as failure:
            execution.poll()
        assert failure.value.code == ("worker_lost" if expired_lease else "timeout")
    finally:
        execution.close()


def test_automatic_retry_cannot_overfill_pending_queue(worker: Harness) -> None:
    job_id = worker.queue()
    # An experiment admitted yesterday can remain queued while the laptop is off.
    worker.clock.advance(86401)
    lease = worker.claim()
    login = worker.client.post(
        "/api/v1/auth/login",
        json={
            "password": "worker-tests-only-not-a-production-password",
        },
        headers={"Origin": ORIGIN},
    )
    assert login.status_code == 200
    worker.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    for index in range(10):
        worker.queue(f"EXP-pending-{index}")
    worker.store.abort(lease, "engine_unavailable", stopped=True)
    assert job_state(worker, job_id) == ("failed", "engine_unavailable")
    with Session(worker.engine) as session:
        assert (
            session.scalar(sa.select(sa.func.count()).select_from(Job).where(Job.phase == "queued"))
            == 10
        )
