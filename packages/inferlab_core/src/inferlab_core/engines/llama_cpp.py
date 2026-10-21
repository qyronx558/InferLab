"""HTTP adapter for an operator-started, single-model llama-server."""

import re
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from decimal import Decimal

import httpx

from ._http import (
    LocalHTTPTransport,
    count_field,
    json_object,
    optional_string,
    parse_json,
    string_field,
    transport_errors,
)
from .errors import EngineResponseError, ModelNotFoundError
from .protocol import (
    EngineHealth,
    GenerationMetadata,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)


@dataclass(frozen=True)
class LlamaServerConfig:
    """Expected startup settings, not runtime HTTP knobs or verified GPU placement."""

    model_alias: str
    gpu_layers: int = 0
    context_tokens: int = 2048

    def __post_init__(self) -> None:
        if not isinstance(self.model_alias, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", self.model_alias
        ):
            raise ValueError("model_alias must be a registry identifier")
        if type(self.gpu_layers) is not int or not 0 <= self.gpu_layers <= 200:
            raise ValueError("gpu_layers must be an integer between 0 and 200")
        if type(self.context_tokens) is not int or not 128 <= self.context_tokens <= 8192:
            raise ValueError("context_tokens must be an integer between 128 and 8192")

    def startup_arguments(self) -> tuple[str, ...]:
        """Return values for manual operator use only; never launch a process."""
        return (
            "--alias",
            self.model_alias,
            "--gpu-layers",
            str(self.gpu_layers),
            "--ctx-size",
            str(self.context_tokens),
            "--parallel",
            "1",
        )


def _milliseconds_as_ns(data: dict[str, object], key: str) -> int | None:
    """Normalize wire units only, without computing benchmark measurements."""
    value = data.get(key)
    if value is None:
        return None
    if type(value) not in (int, float):
        raise EngineResponseError(f"Invalid millisecond field: {key}")
    duration = Decimal(str(value))
    if not duration.is_finite() or duration < 0:
        raise EngineResponseError(f"Invalid millisecond field: {key}")
    return int(duration * 1_000_000)


async def _sse_objects(response: httpx.Response) -> AsyncGenerator[dict[str, object], None]:
    """SSE frames may span lines or TCP chunks. An unterminated frame is incomplete."""
    data: list[str] = []
    first_line = True
    async for line in response.aiter_lines():
        if first_line:
            line = line.removeprefix("\ufeff")
            first_line = False
        if line == "":
            if data:
                yield parse_json("\n".join(data))
                data.clear()
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if field == "data":
            data.append(value.removeprefix(" "))
    if data:
        raise EngineResponseError("Incomplete engine SSE frame")


class LlamaCppEngine(LocalHTTPTransport):
    """Native /completion SSE and shared typed results; no process/model management."""

    def __init__(
        self,
        config: LlamaServerConfig,
        base_url: str = "http://127.0.0.1:8080",
        *,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        super().__init__(base_url, timeout=timeout, client=client)

    def _check_model(self, model: str) -> None:
        if model != self.config.model_alias:
            raise ModelNotFoundError(404)

    def _payload(self, request: GenerationRequest, *, stream: bool) -> dict[str, object]:
        self._check_model(request.model)
        if request.max_tokens > self.config.context_tokens:
            raise ValueError("Output budget exceeds configured context")
        return {
            "model": self.config.model_alias,
            "prompt": request.prompt,
            "n_predict": request.max_tokens,
            "stream": stream,
            "cache_prompt": False,
        }

    def _generation(self, data: dict[str, object]) -> GenerationResult:
        done = data.get("stop")
        if not isinstance(done, bool):
            raise EngineResponseError("Missing or invalid stop flag")
        if (done or "model" in data) and string_field(data, "model") != self.config.model_alias:
            raise EngineResponseError("Engine returned a different model alias")
        if "generation_settings" in data:
            settings = json_object(data["generation_settings"])
            if count_field(settings, "n_ctx") != self.config.context_tokens:
                raise EngineResponseError("Engine context does not match configuration")
        timings = json_object(data["timings"]) if "timings" in data else {}
        return GenerationResult(
            model=self.config.model_alias,
            text=string_field(data, "content", ""),
            done=done,
            done_reason=optional_string(data, "stop_type"),
            metadata=GenerationMetadata(
                prompt_eval_duration_ns=_milliseconds_as_ns(timings, "prompt_ms"),
                eval_duration_ns=_milliseconds_as_ns(timings, "predicted_ms"),
                prompt_eval_count=count_field(data, "tokens_evaluated"),
                eval_count=count_field(timings, "predicted_n"),
            ),
        )

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        data = await self._request(
            "POST", "/completion", self._payload(request, stream=False), model_request=True
        )
        result = self._generation(data)
        if not result.done:
            raise EngineResponseError("Nonstream response was not complete")
        # TODO(owner): benchmark clocks/calculations belong in the future runner.
        return result

    async def stream_generate(
        self, request: GenerationRequest
    ) -> AsyncGenerator[GenerationResult, None]:
        payload = self._payload(request, stream=True)
        with transport_errors():
            async with self._client.stream(
                "POST",
                self._base_url + "/completion",
                json=payload,
                timeout=self._timeout,
                follow_redirects=False,
            ) as response:
                self._status(response, model_request=True)
                async for data in _sse_objects(response):
                    result = self._generation(data)
                    yield result
                    if result.done:
                        return
                raise EngineResponseError("Stream ended without a completion event")

    async def health_check(self) -> EngineHealth:
        health = await self._request("GET", "/health")
        if string_field(health, "status") != "ok":
            raise EngineResponseError("Engine did not report ready status")
        props = await self._request("GET", "/props")
        settings = json_object(props.get("default_generation_settings"))
        if count_field(settings, "n_ctx") != self.config.context_tokens:
            raise EngineResponseError("Engine context does not match configuration")
        if count_field(props, "total_slots") != 1:
            raise EngineResponseError("Adapter requires a single server slot")
        if props.get("is_sleeping", False) is not False:
            raise EngineResponseError("Engine is sleeping or its state is invalid")
        # /health has no version; /props supplies the build without exposing model_path.
        return EngineHealth(version=string_field(props, "build_info"))

    async def model_info(self, model: str) -> ModelInfo:
        self._check_model(model)
        data = await self._request("GET", "/v1/models", model_request=True)
        models = data.get("data")
        if not isinstance(models, list):
            raise EngineResponseError("Invalid model list")
        if not models:
            raise ModelNotFoundError(404)
        if len(models) != 1:
            raise EngineResponseError("Adapter requires a single loaded model")
        entry = json_object(models[0])
        if string_field(entry, "id") != model:
            raise ModelNotFoundError(404)
        meta = json_object(entry["meta"]) if entry.get("meta") is not None else {}
        parameters = count_field(meta, "n_params")
        return ModelInfo(
            model=model, parameter_size=str(parameters) if parameters is not None else None
        )
