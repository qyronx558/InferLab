"""Small engine-neutral transport contract, separate from benchmark/run schemas."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class GenerationRequest:
    model: str
    prompt: str
    max_tokens: int = 128

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise ValueError("model must be a nonempty installed model name")
        if not isinstance(self.prompt, str):
            raise ValueError("prompt must be a string")
        if type(self.max_tokens) is not int or not 1 <= self.max_tokens <= 2048:
            raise ValueError("max_tokens must be an integer between 1 and 2048")


@dataclass(frozen=True)
class GenerationMetadata:
    """Server-reported values only. Missing is None, distinct from zero."""

    total_duration_ns: int | None = None
    load_duration_ns: int | None = None
    prompt_eval_duration_ns: int | None = None
    eval_duration_ns: int | None = None
    prompt_eval_count: int | None = None
    eval_count: int | None = None


@dataclass(frozen=True)
class GenerationResult:
    """A full response or stream event; an event is not necessarily one token."""

    model: str
    text: str
    done: bool
    thinking: str = ""
    done_reason: str | None = None
    metadata: GenerationMetadata = field(default_factory=GenerationMetadata)


@dataclass(frozen=True)
class EngineHealth:
    """Successful reachability check, not model/GPU readiness. Failures raise."""

    version: str


@dataclass(frozen=True)
class ModelInfo:
    model: str
    format: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization_level: str | None = None
    capabilities: tuple[str, ...] = ()


class EngineProtocol(Protocol):
    async def generate(self, request: GenerationRequest) -> GenerationResult: ...

    def stream_generate(
        self, request: GenerationRequest
    ) -> AsyncGenerator[GenerationResult, None]: ...

    async def health_check(self) -> EngineHealth: ...

    async def model_info(self, model: str) -> ModelInfo: ...

    async def aclose(self) -> None: ...
