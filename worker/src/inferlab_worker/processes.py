"""Bounded, spawn-only Python execution. No shell, TCP listener or result pickle."""

import importlib
import json
import multiprocessing
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from multiprocessing.process import BaseProcess
from pathlib import Path
from typing import Any, Protocol, cast

from inferlab_api.contracts import ExperimentConfig

from .contracts import ExecutionIdentity, Lease, RunBatch, RunnerFailure, RunnerPlugin
from .locking import GPULock

MAX_RESULT_BYTES = 262144
FACTORY_PATTERN = r"[A-Za-z_][A-Za-z0-9_.]*:[A-Za-z_][A-Za-z0-9_]*"
ERRORS = {"validation_error", "worker_lost", "engine_unavailable", "out_of_memory", "timeout"}


class Execution(Protocol):
    def poll(self) -> RunBatch | None: ...
    def close(self) -> bool: ...
    def renew(self, expires_at: datetime) -> None: ...


class Backend(Protocol):
    def start(
        self, lease: Lease, execution_lock: Path, deadline: float | None = None
    ) -> Execution: ...
    def stop_and_confirm(self, execution_lock: Path) -> bool: ...


@dataclass(frozen=True)
class FileCancellation:
    path: str

    def is_set(self) -> bool:
        return Path(self.path).exists()


def _plugin(factory: str) -> RunnerPlugin:
    module, name = factory.split(":")
    creator = getattr(importlib.import_module(module), name)
    return cast(RunnerPlugin, creator())


def _write_result(directory: str, data: dict[str, Any]) -> None:
    encoded = json.dumps(data, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > MAX_RESULT_BYTES:
        encoded = b'{"error":"validation_error"}'
    path = Path(directory) / "outcome.tmp"
    path.write_bytes(encoded)
    path.replace(Path(directory) / "outcome.json")


def _watch_parent(deadline: float, directory: str | None = None) -> None:
    parent = multiprocessing.parent_process()
    exit_code = 125
    while parent is not None and parent.is_alive() and time.monotonic() < deadline:
        if directory is not None:
            try:
                path = Path(directory) / "lease.json"
                if path.stat().st_size > 512:
                    break
                renewal = json.loads(path.read_bytes())
                expiry = datetime.fromisoformat(renewal["expires_at"])
                if datetime.now(UTC) >= expiry or time.monotonic() >= renewal["renewed"] + 120:
                    if expiry == datetime.fromisoformat(renewal["job_deadline_at"]):
                        exit_code = 124
                    break
            except (OSError, ValueError, KeyError, TypeError):
                break
        time.sleep(0.1)
    if time.monotonic() >= deadline:
        exit_code = 124
    os._exit(exit_code)  # A dead/blocked supervisor cannot renew this execution.


def _execute(
    factory: str,
    directory: str,
    config_json: str,
    attempt: int,
    execution_lock: str,
    identity_json: str,
    deadline: float,
) -> None:
    try:
        with GPULock(Path(execution_lock)):
            threading.Thread(target=_watch_parent, args=(deadline, directory), daemon=True).start()
            parent = multiprocessing.parent_process()
            if parent is None or not parent.is_alive():
                raise RunnerFailure("worker_lost")
            if time.monotonic() >= deadline:
                raise RunnerFailure("timeout")
            config = ExperimentConfig.model_validate_json(config_json)
            plugin = _plugin(factory)
            if not plugin.verify_installation(
                config, ExecutionIdentity.model_validate_json(identity_json)
            ):
                raise RunnerFailure("validation_error")
            batch = plugin.run(config, attempt, FileCancellation(str(Path(directory) / "cancel")))
            checked = RunBatch.model_validate(batch.model_dump())
            _write_result(directory, {"batch": checked.model_dump(mode="json")})
    except RunnerFailure as error:
        _write_result(
            directory, {"error": error.code if error.code in ERRORS else "validation_error"}
        )
    except MemoryError:
        _write_result(directory, {"error": "out_of_memory"})
    except ValueError:
        _write_result(directory, {"error": "validation_error"})
    except Exception:
        _write_result(directory, {"error": "worker_lost"})


def _probe(factory: str, directory: str, execution_lock: str, deadline: float) -> None:
    try:
        with GPULock(Path(execution_lock)):
            threading.Thread(target=_watch_parent, args=(deadline,), daemon=True).start()
            parent = multiprocessing.parent_process()
            stopped = (
                parent is not None
                and parent.is_alive()
                and _plugin(factory).stop_and_confirm() is True
            )
    except Exception:
        stopped = False
    _write_result(directory, {"stopped": stopped})


def _kill(process: BaseProcess) -> bool:
    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
    if process.is_alive():
        process.kill()
        process.join(timeout=1)
    return not process.is_alive()


def _read_result(directory: str) -> dict[str, Any]:
    path = Path(directory) / "outcome.json"
    if not path.is_file() or path.stat().st_size > MAX_RESULT_BYTES:
        raise ValueError("Missing or oversized result")
    data: object = json.loads(path.read_bytes())
    if not isinstance(data, dict):
        raise ValueError("Invalid result")
    return data


class ProcessExecution:
    def __init__(
        self,
        factory: str,
        lease: Lease,
        grace_seconds: float,
        execution_lock: Path,
        deadline: float,
    ) -> None:
        self.directory = tempfile.TemporaryDirectory(prefix="inferlab-run-")
        self.job_deadline_at = lease.deadline_at
        self.renew(lease.expires_at)
        self.grace_seconds = grace_seconds
        self.process = multiprocessing.get_context("spawn").Process(
            target=_execute,
            args=(
                factory,
                self.directory.name,
                lease.config.model_dump_json(),
                lease.attempt,
                str(execution_lock),
                lease.identity.model_dump_json(),
                deadline,
            ),
            daemon=True,
        )
        self.closed = False
        self.process.start()

    def renew(self, expires_at: datetime) -> None:
        path = Path(self.directory.name) / "lease.tmp"
        path.write_text(
            json.dumps(
                {
                    "expires_at": expires_at.isoformat(),
                    "renewed": time.monotonic(),
                    "job_deadline_at": self.job_deadline_at.isoformat(),
                }
            ),
            encoding="utf-8",
        )
        for attempt in range(5):
            try:
                path.replace(Path(self.directory.name) / "lease.json")
                return
            except PermissionError:
                # Windows can briefly deny replacement while the watchdog reads
                # the old file. Retry briefly; never grant authority on failure.
                if attempt == 4:
                    raise
                time.sleep(0.01)

    def poll(self) -> RunBatch | None:
        if self.process.is_alive():
            return None
        self.process.join(timeout=0)
        if self.process.exitcode == 124:
            raise RunnerFailure("timeout")
        if self.process.exitcode != 0:
            raise RunnerFailure("worker_lost")
        try:
            data = _read_result(self.directory.name)
            if "error" in data:
                code = data["error"]
                raise RunnerFailure(code if code in ERRORS else "validation_error")
            return RunBatch.model_validate(data.get("batch"))
        except (ValueError, OSError):
            raise RunnerFailure("validation_error") from None

    def close(self) -> bool:
        if self.closed:
            return True
        if self.process.is_alive():
            try:
                Path(self.directory.name, "cancel").touch()
            except OSError:
                pass  # Hard termination remains available if cooperative signalling fails.
            self.process.join(timeout=self.grace_seconds)
        stopped = _kill(self.process)
        if stopped:
            self.process.close()
            self.closed = True
            try:
                self.directory.cleanup()
            except OSError:
                pass  # A cleanup failure must not mask a confirmed process exit.
        return stopped


class ProcessBackend:
    def __init__(self, factory: str, *, grace_seconds: float = 5, probe_seconds: float = 5) -> None:
        if re.fullmatch(FACTORY_PATTERN, factory) is None:
            raise ValueError("Plugin must be an operator-configured module:factory")
        if not 0 <= grace_seconds <= 5 or not 0 < probe_seconds <= 5:
            raise ValueError("Stop/probe bounds exceed the private worker policy")
        self.factory, self.grace_seconds, self.probe_seconds = factory, grace_seconds, probe_seconds

    def start(
        self, lease: Lease, execution_lock: Path, deadline: float | None = None
    ) -> ProcessExecution:
        return ProcessExecution(
            self.factory,
            lease,
            self.grace_seconds,
            execution_lock,
            deadline if deadline is not None else time.monotonic() + lease.remaining_seconds,
        )

    def stop_and_confirm(self, execution_lock: Path) -> bool:
        with tempfile.TemporaryDirectory(prefix="inferlab-stop-") as directory:
            process = multiprocessing.get_context("spawn").Process(
                target=_probe,
                args=(
                    self.factory,
                    directory,
                    str(execution_lock),
                    time.monotonic() + self.probe_seconds,
                ),
                daemon=True,
            )
            process.start()
            process.join(timeout=self.probe_seconds)
            if process.is_alive():
                if _kill(process):
                    process.close()
                return False
            try:
                return process.exitcode == 0 and _read_result(directory).get("stopped") is True
            except (ValueError, OSError):
                return False
            finally:
                process.close()
