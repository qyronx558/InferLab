"""Protocol parity with HTTP fixtures only: no engines, shells, downloads or GPU."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass
from typing import Literal

import httpx
import pytest

from inferlab_core.engines import (
    EngineConnectionError,
    EngineError,
    EngineHealth,
    EngineHTTPError,
    EngineProtocol,
    EngineRemoteError,
    EngineResponseError,
    EngineTimeoutError,
    GenerationRequest,
    GenerationResult,
    LlamaCppEngine,
    LlamaServerConfig,
    ModelInfo,
    ModelNotFoundError,
    OllamaEngine,
)

REQUEST = GenerationRequest(model="local-demo", prompt="private prompt", max_tokens=8)


@dataclass(frozen=True)
class Case:
    kind: Literal["ollama", "llama.cpp"]

    def build(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        timeout: httpx.Timeout | None = None,
        base_url: str = "http://127.0.0.1:8080",
    ) -> OllamaEngine | LlamaCppEngine:
        if self.kind == "ollama":
            return OllamaEngine(base_url, client=client, timeout=timeout)
        return LlamaCppEngine(
            LlamaServerConfig(model_alias=REQUEST.model), base_url, client=client, timeout=timeout
        )

    @property
    def generate_path(self) -> str:
        return "/api/generate" if self.kind == "ollama" else "/completion"

    def event(self, text: str = "", *, done: bool = False) -> dict[str, object]:
        if self.kind == "ollama":
            data: dict[str, object] = {"model": REQUEST.model, "response": text, "done": done}
            if done:
                data.update(
                    prompt_eval_count=3,
                    eval_count=2,
                    load_duration=0,
                    prompt_eval_duration=12_345,
                    eval_duration=98_765,
                )
            return data
        data = {"model": REQUEST.model, "content": text, "stop": done}
        if done:
            data.update(
                tokens_evaluated=3,
                stop_type="eos",
                timings={"predicted_n": 2, "prompt_ms": 0.012345, "predicted_ms": 0.098765},
                generation_settings={"n_ctx": 2048},
            )
        return data

    def frame(self, data: dict[str, object]) -> bytes:
        encoded = json.dumps(data, ensure_ascii=False)
        return (encoded + "\n" if self.kind == "ollama" else f"data: {encoded}\r\n\r\n").encode()


@pytest.fixture(params=[Case("ollama"), Case("llama.cpp")], ids=["ollama", "llama.cpp"])
def case(request: pytest.FixtureRequest) -> Case:
    assert isinstance(request.param, Case)
    return request.param


class Stream(httpx.AsyncByteStream):
    def __init__(
        self, chunks: list[bytes], *, block: bool = False, failure: httpx.RequestError | None = None
    ) -> None:
        self.chunks = chunks
        self.block = block
        self.failure = failure
        self.waiting = asyncio.Event()
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk
        if self.failure is not None:
            raise self.failure
        if self.block:
            self.waiting.set()
            await asyncio.Event().wait()

    async def aclose(self) -> None:
        self.closed = True


def test_generate_protocol_and_normalized_metadata(case: Case) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST" and request.url.path == case.generate_path
            payload = json.loads(request.content)
            assert payload["model"] == REQUEST.model and payload["prompt"] == REQUEST.prompt
            assert payload["stream"] is False
            if case.kind == "llama.cpp":
                assert payload["n_predict"] == 8 and payload["cache_prompt"] is False
                assert "gpu_layers" not in payload and "n_ctx" not in payload
            else:
                assert payload["options"] == {"num_predict": 8}
            assert request.extensions["timeout"] == {"connect": 1, "read": 2, "write": 3, "pool": 4}
            return httpx.Response(200, json=case.event("Hello", done=True))

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async with case.build(
                client, timeout=httpx.Timeout(connect=1, read=2, write=3, pool=4)
            ) as engine:
                protocol: EngineProtocol = engine
                result = await protocol.generate(REQUEST)
                assert isinstance(result, GenerationResult)
                assert result.model == REQUEST.model and result.text == "Hello" and result.done
                assert result.metadata.prompt_eval_count == 3 and result.metadata.eval_count == 2
                assert result.metadata.prompt_eval_duration_ns == 12_345
                assert result.metadata.eval_duration_ns == 98_765
                if case.kind == "llama.cpp":
                    assert result.metadata.load_duration_ns is None
                    assert result.metadata.total_duration_ns is None
            assert not client.is_closed

    asyncio.run(scenario())


def test_stream_split_utf8_final_text_and_missing_values(case: Case) -> None:
    async def scenario() -> None:
        wire = b"\n" + b"".join(
            case.frame(event)
            for event in (case.event("hé"), case.event(), case.event("!", done=True))
        )
        stream = Stream([wire[index : index + 1] for index in range(len(wire))])

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == case.generate_path
            assert json.loads(request.content)["stream"] is True
            return httpx.Response(200, stream=stream)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = [event async for event in case.build(client).stream_generate(REQUEST)]
            assert [event.text for event in events] == ["hé", "", "!"]
            assert events[0].metadata.eval_count is None and events[-1].done
            assert events[-1].metadata.eval_count == 2
            assert stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status,error",
    [
        (404, ModelNotFoundError),
        (503, EngineHTTPError),
        (429, EngineHTTPError),
        (302, EngineHTTPError),
    ],
)
@pytest.mark.parametrize("streaming", [False, True])
def test_http_errors_do_not_follow_redirects_retry_or_leak_bodies(
    case: Case, status: int, error: type[EngineHTTPError], streaming: bool
) -> None:
    async def scenario() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert request.url.path == case.generate_path
            return httpx.Response(
                status,
                headers={"location": "https://example.com"},
                json={"error": "private prompt and paths"},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            with pytest.raises(error) as caught:
                if streaming:
                    async for _ in case.build(client).stream_generate(REQUEST):
                        pass
                else:
                    await case.build(client).generate(REQUEST)
            assert caught.value.status_code == status and calls == 1
            assert "private" not in str(caught.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "exception,error",
    [
        (httpx.ConnectTimeout, EngineTimeoutError),
        (httpx.ReadTimeout, EngineTimeoutError),
        (httpx.ConnectError, EngineConnectionError),
        (httpx.RemoteProtocolError, EngineConnectionError),
    ],
)
@pytest.mark.parametrize("streaming", [False, True])
def test_transport_failures_share_error_types(
    case: Case, exception: type[httpx.RequestError], error: type[EngineError], streaming: bool
) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise exception("private details", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(error) as caught:
                if streaming:
                    async for _ in case.build(client).stream_generate(REQUEST):
                        pass
                else:
                    await case.build(client).generate(REQUEST)
            assert "private" not in str(caught.value)

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["inline", "truncated", "invalid-json"])
def test_bad_streams_close_with_typed_errors(case: Case, failure: str) -> None:
    async def scenario() -> None:
        wire = case.frame(case.event("partial"))
        if failure == "inline":
            wire += case.frame({"error": {"message": "private details"}})
        elif failure == "invalid-json":
            wire += b"not-json\n" if case.kind == "ollama" else b"data: not-json\n\n"
        stream = Stream([wire])
        expected = EngineRemoteError if failure == "inline" else EngineResponseError
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            with pytest.raises(expected) as caught:
                async for _ in case.build(client).stream_generate(REQUEST):
                    pass
            assert stream.closed and "private" not in str(caught.value)

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_cancellation_propagates_and_closes_response(case: Case, streaming: bool) -> None:
    async def scenario() -> None:
        stream = Stream([case.frame(case.event())] if streaming else [], block=True)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:

            async def consume() -> None:
                engine = case.build(client)
                if streaming:
                    async for _ in engine.stream_generate(REQUEST):
                        pass
                else:
                    await engine.generate(REQUEST)

            task = asyncio.create_task(consume())
            await asyncio.wait_for(stream.waiting.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stream.closed and not client.is_closed

    asyncio.run(scenario())


def test_early_exit_closes_response(case: Case) -> None:
    async def scenario() -> None:
        stream = Stream([case.frame(case.event("partial"))], block=True)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            async with aclosing(case.build(client).stream_generate(REQUEST)) as events:
                async for _ in events:
                    break
            assert stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_mid_body_timeout_closes_response(case: Case, streaming: bool) -> None:
    async def scenario() -> None:
        stream = Stream([], failure=httpx.ReadTimeout("private details"))
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            with pytest.raises(EngineTimeoutError):
                if streaming:
                    async for _ in case.build(client).stream_generate(REQUEST):
                        pass
                else:
                    await case.build(client).generate(REQUEST)
            assert stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com",
        "http://user:secret@localhost",
        "http://localhost/api",
        "http://localhost/?secret=1",
        "http://localhost/#fragment",
    ],
)
def test_loopback_origin_policy(case: Case, url: str) -> None:
    with pytest.raises(ValueError):
        case.build(base_url=url)


@pytest.mark.parametrize("seconds", [None, 0.0, -1.0, float("inf"), float("nan")])
def test_finite_timeouts_required(case: Case, seconds: float | None) -> None:
    with pytest.raises(ValueError):
        case.build(timeout=httpx.Timeout(seconds))


def test_owned_client_closes(case: Case) -> None:
    async def scenario() -> None:
        async with case.build() as engine:
            pass
        with pytest.raises(RuntimeError, match="closed"):
            await engine.health_check()

    asyncio.run(scenario())


def test_health_and_model_info_share_typed_contract_without_generation(case: Case) -> None:
    async def scenario() -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if case.kind == "ollama":
                if request.url.path == "/api/version":
                    return httpx.Response(200, json={"version": "demo-build"})
                assert request.url.path == "/api/show"
                return httpx.Response(200, json={"details": {}})
            assert request.method == "GET"
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/props":
                return httpx.Response(
                    200,
                    json={
                        "build_info": "demo-build",
                        "total_slots": 1,
                        "default_generation_settings": {"n_ctx": 2048},
                    },
                )
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json={"data": [{"id": REQUEST.model, "meta": None}]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            protocol: EngineProtocol = case.build(client)
            health = await protocol.health_check()
            model = await protocol.model_info(REQUEST.model)
            assert isinstance(health, EngineHealth) and health.version == "demo-build"
            assert isinstance(model, ModelInfo) and model.model == REQUEST.model
            assert model.parameter_size is None and model.quantization_level is None
            assert case.generate_path not in paths
            assert len(paths) == (2 if case.kind == "ollama" else 3)

    asyncio.run(scenario())
