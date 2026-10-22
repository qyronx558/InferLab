"""Worker policy and trusted local plugin interfaces, without benchmark algorithms."""

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal, Protocol

from pydantic import Field

from inferlab_api.contracts import (
    Checksum,
    Contract,
    ExperimentConfig,
    Identifier,
    Registry,
    RunMetrics,
    ShortText,
)


class WorkerPolicy(Contract):
    registry: Registry
    gpu_device_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=2048)] = 2048
    max_runtime_seconds: Annotated[int, Field(strict=True, ge=1, le=3600)] = 3600
    max_gpu_layers: Annotated[int, Field(strict=True, ge=0, le=200)] = 200


class RunBatch(Contract):
    runs: Annotated[list[RunMetrics], Field(min_length=1, max_length=25)]


class ExecutionIdentity(Contract):
    device_name: ShortText
    driver_version: ShortText
    workload_sha256: Checksum
    methodology_version: Identifier


class RunnerFailure(Exception):
    """Only worker_lost/engine_unavailable are eligible for automatic retry."""

    def __init__(
        self,
        code: Literal[
            "validation_error",
            "worker_lost",
            "engine_unavailable",
            "out_of_memory",
            "timeout",
        ],
    ) -> None:
        self.code = code
        super().__init__(code)


class Cancellation(Protocol):
    def is_set(self) -> bool: ...


class RunnerPlugin(Protocol):
    """Trusted operator code. Receives approved IDs only, never request code/paths.

    verify_installation must check actual installed model checksum/revision and
    engine build without downloading/loading a model. run must apply the bounded
    config to engine requests, honor cancellation and return all expected runs.
    stop_and_confirm must stop/confirm all worker-owned engine work, including
    orphaned requests after restart. An HTTP disconnect alone is not confirmation.
    Implementations use bounded I/O and dedicated local engines. Metric math and
    benchmark run generation remain owner-authored; no default plugin is supplied.
    """

    def verify_installation(
        self, config: ExperimentConfig, expected: ExecutionIdentity
    ) -> bool: ...

    def run(
        self, config: ExperimentConfig, attempt: int, cancellation: Cancellation
    ) -> RunBatch: ...

    def stop_and_confirm(self) -> bool: ...


@dataclass(frozen=True)
class Lease:
    job_id: str
    worker_id: str
    attempt: int
    token: int
    config: ExperimentConfig
    deadline_at: datetime
    remaining_seconds: float
    identity: ExecutionIdentity
    expires_at: datetime


@dataclass(frozen=True)
class Heartbeat:
    cancelled: bool
    expires_at: datetime


class LeaseLost(Exception):
    pass


class CompletionConflict(Exception):
    pass
