"""Local Ollama HTTP plumbing only: no clocks, metric math, retries or model pulls."""

import json
import math
from collections.abc import AsyncGenerator, Iterator
from contextlib import contextmanager
from typing import Self

import httpx

from .errors import (
    EngineConnectionError,
    EngineHTTPError,
    EngineRemoteError,
    EngineResponseError,
    EngineTimeoutError,
    ModelNotFoundError,
)
from .protocol import (
    EngineHealth,
    GenerationMetadata,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)


@contextmanager
def _transport_errors() -> Iterator[None]:
    try:
        yield
    except httpx.TimeoutException:
        raise EngineTimeoutError("Engine request timed out") from None
    except httpx.RequestError:
        raise EngineConnectionError("Engine transport failed") from None


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise EngineResponseError("Expected a JSON object")
    result: dict[str, object] = dict(value)
    if "error" in result:
        raise EngineRemoteError("Engine reported an error")
    return result


def _json(value: str | bytes) -> dict[str, object]:
    try:
        return _object(json.loads(value))
    except (ValueError, UnicodeError):
        raise EngineResponseError("Invalid engine JSON") from None


def _text(data: dict[str, object], key: str, default: str | None = None) -> str:
    value = data.get(key, default)
    if not isinstance(value, str):
        raise EngineResponseError(f"Invalid string field: {key}")
    return value


def _optional_text(data: dict[str, object], key: str) -> str | None:
    return None if data.get(key) is None else _text(data, key)


def _count(data: dict[str, object], key: str) -> int | None:
    value = data.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise EngineResponseError(f"Invalid nonnegative integer field: {key}")
    return value


def _generation(data: dict[str, object]) -> GenerationResult:
    done = data.get("done")
    if not isinstance(done, bool):
        raise EngineResponseError("Missing or invalid done flag")
    return GenerationResult(
        model=_text(data, "model"),
        text=_text(data, "response", ""),
        thinking=_text(data, "thinking", ""),
        done=done,
        done_reason=_optional_text(data, "done_reason"),
        metadata=GenerationMetadata(
            total_duration_ns=_count(data, "total_duration"),
            load_duration_ns=_count(data, "load_duration"),
            prompt_eval_duration_ns=_count(data, "prompt_eval_duration"),
            eval_duration_ns=_count(data, "eval_duration"),
            prompt_eval_count=_count(data, "prompt_eval_count"),
            eval_count=_count(data, "eval_count"),
        ),
    )


class OllamaEngine:
    """Async loopback adapter. Injected clients remain owned by their caller."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        url = httpx.URL(base_url)
        if (
            url.scheme not in {"http", "https"}
            or url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.userinfo
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError("Ollama base_url must be a loopback origin without credentials")
        self._base_url = str(url).rstrip("/")
        self._timeout = timeout or httpx.Timeout(connect=5, read=60, write=10, pool=5)
        for duration in self._timeout.as_dict().values():
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise ValueError("All HTTP timeouts must be finite and positive")
        self._owns_client = client is None
        self._client = client if client is not None else httpx.AsyncClient(trust_env=False)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _status(response: httpx.Response, *, model_request: bool = False) -> None:
        if model_request and response.status_code == 404:
            raise ModelNotFoundError(404)
        if not response.is_success:
            raise EngineHTTPError(response.status_code)

    async def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        with _transport_errors():
            response = await self._client.request(
                method,
                self._base_url + path,
                json=payload,
                timeout=self._timeout,
                follow_redirects=False,
            )
            self._status(response, model_request=path != "/api/version")
            return _json(response.content)

    @staticmethod
    def _payload(request: GenerationRequest, *, stream: bool) -> dict[str, object]:
        return {
            "model": request.model,
            "prompt": request.prompt,
            "stream": stream,
            "options": {"num_predict": request.max_tokens},
        }

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        data = await self._request("POST", "/api/generate", self._payload(request, stream=False))
        result = _generation(data)
        if not result.done:
            raise EngineResponseError("Nonstream response was not complete")
        # TODO(owner): record benchmark timestamps and calculate metrics outside this adapter.
        return result

    async def stream_generate(
        self, request: GenerationRequest
    ) -> AsyncGenerator[GenerationResult, None]:
        with _transport_errors():
            async with self._client.stream(
                "POST",
                self._base_url + "/api/generate",
                json=self._payload(request, stream=True),
                timeout=self._timeout,
                follow_redirects=False,
            ) as response:
                self._status(response, model_request=True)
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    result = _generation(_json(line))
                    # TODO(owner): observe content events; chunks are not token timestamps.
                    yield result
                    if result.done:
                        return
                raise EngineResponseError("Stream ended without a completion event")

    async def health_check(self) -> EngineHealth:
        data = await self._request("GET", "/api/version")
        return EngineHealth(version=_text(data, "version"))

    async def model_info(self, model: str) -> ModelInfo:
        GenerationRequest(model=model, prompt="")  # Validate without executing generation.
        data = await self._request("POST", "/api/show", {"model": model})
        details = _object(data.get("details"))
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) for item in capabilities
        ):
            raise EngineResponseError("Invalid capabilities")
        return ModelInfo(
            model=model,
            format=_optional_text(details, "format"),
            family=_optional_text(details, "family"),
            parameter_size=_optional_text(details, "parameter_size"),
            quantization_level=_optional_text(details, "quantization_level"),
            capabilities=tuple(capabilities),
        )
