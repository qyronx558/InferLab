"""Private polling supervisor. Only the spawned owner plugin performs inference."""

import time
from collections.abc import Callable
from pathlib import Path
from threading import Event

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .contracts import CompletionConflict, Lease, LeaseLost, RunnerFailure
from .locking import GPULock, WorkerAlreadyRunning
from .processes import Backend, Execution
from .store import HEARTBEAT_SECONDS, WorkerStore


class Worker:
    def __init__(
        self,
        store: WorkerStore,
        backend: Backend,
        worker_id: str,
        lock_file: Path,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wait: Callable[[Event, float], bool] = lambda event, seconds: event.wait(seconds),
    ) -> None:
        self.store, self.backend, self.worker_id = store, backend, worker_id
        self.lock_file, self.monotonic, self.wait = lock_file, monotonic, wait
        self.execution_lock = lock_file.with_name(lock_file.name + ".execution")

    def _confirm_stopped(self) -> bool:
        try:
            with GPULock(self.execution_lock):
                pass
            return self.backend.stop_and_confirm(self.execution_lock)
        except WorkerAlreadyRunning:
            return False

    def serve(self, stop: Event, *, once: bool = False, resume: bool = False) -> None:
        with GPULock(self.lock_file):
            # An orphan owns the execution lock until its parent-death watchdog
            # exits. Never inspect engine idle state ahead of that boundary.
            while not stop.is_set():
                try:
                    with GPULock(self.execution_lock):
                        pass
                    confirmed = self.backend.stop_and_confirm(self.execution_lock)
                    break
                except WorkerAlreadyRunning:
                    if once:
                        return
                    self.wait(stop, 1)
            else:
                return
            self.store.reconcile(stopped=confirmed)
            if not confirmed:
                return  # Persisted pause; operator intervention is required.
            if resume:
                self.store.resume(stopped=True)
            while not stop.is_set():
                if self.store.presence(self.worker_id):
                    return  # A verified stop does not implicitly undo an operator pause.
                self.store.reconcile(stopped=True)
                lease = self.store.claim(self.worker_id)
                if lease is not None:
                    self._execute(lease, stop)
                if once:
                    return
                self.wait(stop, 5)

    def _execute(self, lease: Lease, stop: Event) -> None:
        execution: Execution | None = None
        deadline = self.monotonic() + lease.remaining_seconds
        heartbeat_at = self.monotonic() + HEARTBEAT_SECONDS
        error = "worker_lost"
        try:
            self.store.start(lease)
            execution = self.backend.start(lease, self.execution_lock, deadline)
            while True:
                if stop.is_set():
                    break
                if self.monotonic() >= deadline:
                    error = "timeout"
                    break
                if self.store.status(lease):
                    error = "cancelled"
                    break
                if self.monotonic() >= heartbeat_at:
                    heartbeat = self.store.heartbeat(lease)
                    execution.renew(heartbeat.expires_at)
                    if heartbeat.cancelled:
                        error = "cancelled"
                        break
                    heartbeat_at = self.monotonic() + HEARTBEAT_SECONDS
                batch = execution.poll()
                if batch is not None:
                    child_stopped = execution.close()
                    confirmed = self._confirm_stopped() and child_stopped
                    if not confirmed:
                        error = "worker_lost"
                        break
                    if self.monotonic() >= deadline:
                        error = "timeout"
                        break
                    self.store.complete(lease, batch)
                    return
                self.wait(stop, min(1, max(0, deadline - self.monotonic())))
        except RunnerFailure as failure:
            error = failure.code
        except ValueError:
            error = "validation_error"
        except (LeaseLost, CompletionConflict):
            error = "worker_lost"
        except IntegrityError:
            error = "validation_error"
        except OSError:
            error = "worker_lost"
        except SQLAlchemyError:
            # No success is inferred from unavailable storage. Startup recovery
            # must inspect the still-active lease before any later execution.
            if execution is not None:
                execution.close()
            self._confirm_stopped()
            raise
        finally:
            if execution is not None:
                child_stopped = execution.close()
            else:
                child_stopped = True
        confirmed = self._confirm_stopped() and child_stopped
        try:
            self.store.abort(lease, error, stopped=confirmed)
        except LeaseLost:
            # A newer token owns the record; stale code cannot alter its results.
            if not confirmed:
                self.store.pause()
