"""Local Ollama HTTP plumbing only: no clocks, metric math, retries or model pulls."""

from collections.abc import AsyncGenerator

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
from .errors import EngineResponseError
from .protocol import (
    EngineHealth,
    GenerationMetadata,
    GenerationRequest,
    GenerationResult,
    ModelInfo,
)


def _generation(data: dict[str, object]) -> GenerationResult:
    done = data.get("done")
    if not isinstance(done, bool):
        raise EngineResponseError("Missing or invalid done flag")
    return GenerationResult(
        model=string_field(data, "model"),
        text=string_field(data, "response", ""),
        thinking=string_field(data, "thinking", ""),
        done=done,
        done_reason=optional_string(data, "done_reason"),
        metadata=GenerationMetadata(
            total_duration_ns=count_field(data, "total_duration"),
            load_duration_ns=count_field(data, "load_duration"),
            prompt_eval_duration_ns=count_field(data, "prompt_eval_duration"),
            eval_duration_ns=count_field(data, "eval_duration"),
            prompt_eval_count=count_field(data, "prompt_eval_count"),
            eval_count=count_field(data, "eval_count"),
        ),
    )


class OllamaEngine(LocalHTTPTransport):
    """Async loopback adapter. Injected clients remain owned by their caller."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        *,
        timeout: httpx.Timeout | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url, timeout=timeout, client=client)

    @staticmethod
    def _payload(request: GenerationRequest, *, stream: bool) -> dict[str, object]:
        return {
            "model": request.model,
            "prompt": request.prompt,
            "stream": stream,
            "options": {"num_predict": request.max_tokens},
        }

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        data = await self._request(
            "POST", "/api/generate", self._payload(request, stream=False), model_request=True
        )
        result = _generation(data)
        if not result.done:
            raise EngineResponseError("Nonstream response was not complete")
        # TODO(owner): record benchmark timestamps and calculate metrics outside this adapter.
        return result

    async def stream_generate(
        self, request: GenerationRequest
    ) -> AsyncGenerator[GenerationResult, None]:
        with transport_errors():
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
                    result = _generation(parse_json(line))
                    # TODO(owner): observe content events; chunks are not token timestamps.
                    yield result
                    if result.done:
                        return
                raise EngineResponseError("Stream ended without a completion event")

    async def health_check(self) -> EngineHealth:
        data = await self._request("GET", "/api/version")
        return EngineHealth(version=string_field(data, "version"))

    async def model_info(self, model: str) -> ModelInfo:
        GenerationRequest(model=model, prompt="")  # Validate without executing generation.
        data = await self._request("POST", "/api/show", {"model": model}, model_request=True)
        details = json_object(data.get("details"))
        capabilities = data.get("capabilities", [])
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) for item in capabilities
        ):
            raise EngineResponseError("Invalid capabilities")
        return ModelInfo(
            model=model,
            format=optional_string(details, "format"),
            family=optional_string(details, "family"),
            parameter_size=optional_string(details, "parameter_size"),
            quantization_level=optional_string(details, "quantization_level"),
            capabilities=tuple(capabilities),
        )
