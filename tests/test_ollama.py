"""HTTP-only fixtures. No server, models, GPU, clocks or benchmark calculations."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import aclosing

import httpx
import pytest

from inferlab_core.engines import (
    EngineConnectionError,
    EngineError,
    EngineHTTPError,
    EngineProtocol,
    EngineRemoteError,
    EngineResponseError,
    EngineTimeoutError,
    GenerationRequest,
    ModelNotFoundError,
    OllamaEngine,
)

REQUEST = GenerationRequest(model="local-demo:latest", prompt="private prompt", max_tokens=8)
FINAL: dict[str, object] = {
    "model": REQUEST.model,
    "response": "Hi",
    "done": True,
    "done_reason": "stop",
    "total_duration": 1_234_567_890,
    "load_duration": 0,
    "prompt_eval_duration": 12_345,
    "eval_duration": 98_765,
    "prompt_eval_count": 3,
    "eval_count": 2,
}


class ByteStream(httpx.AsyncByteStream):
    def __init__(
        self,
        chunks: list[bytes],
        *,
        block: bool = False,
        failure: httpx.RequestError | None = None,
    ) -> None:
        self.chunks = chunks
        self.block = block
        self.waiting = asyncio.Event()
        self.closed = False
        self.failure = failure

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


def test_generate_preserves_nanoseconds_and_request_options() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url == "http://127.0.0.1:11434/api/generate"
            assert json.loads(request.content) == {
                "model": REQUEST.model,
                "prompt": REQUEST.prompt,
                "stream": False,
                "options": {"num_predict": 8},
            }
            assert request.extensions["timeout"] == {
                "connect": 5,
                "read": 60,
                "write": 10,
                "pool": 5,
            }
            return httpx.Response(200, json=FINAL)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            async with OllamaEngine(client=client) as adapter:
                engine: EngineProtocol = adapter  # Also checks structural protocol conformance.
                result = await engine.generate(REQUEST)
                assert result.text == "Hi" and result.done
                assert result.done_reason == "stop"
                assert result.metadata.total_duration_ns == 1_234_567_890
                assert result.metadata.load_duration_ns == 0
                assert result.metadata.prompt_eval_duration_ns == 12_345
                assert result.metadata.eval_duration_ns == 98_765
                assert result.metadata.prompt_eval_count == 3
                assert result.metadata.eval_count == 2
            assert not client.is_closed

    asyncio.run(scenario())


def test_health_and_allowlisted_model_info_never_generate_or_pull() -> None:
    async def scenario() -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            paths.append(request.url.path)
            if request.url.path == "/api/version":
                assert request.method == "GET"
                return httpx.Response(200, json={"version": "fixture-version"})
            assert request.method == "POST" and request.url.path == "/api/show"
            assert json.loads(request.content) == {"model": REQUEST.model}
            return httpx.Response(
                200,
                json={
                    "details": {
                        "format": "gguf",
                        "family": "demo",
                        "parameter_size": "1B",
                        "quantization_level": "Q4_K_M",
                    },
                    "capabilities": ["completion"],
                    "modelfile": "private local filesystem path",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            engine = OllamaEngine(client=client)
            assert (await engine.health_check()).version == "fixture-version"
            info = await engine.model_info(REQUEST.model)
            assert (info.model, info.format, info.family) == (REQUEST.model, "gguf", "demo")
            assert (info.parameter_size, info.quantization_level) == ("1B", "Q4_K_M")
            assert info.capabilities == ("completion",)
            assert "private" not in repr(info)
            assert paths == ["/api/version", "/api/show"]

    asyncio.run(scenario())


def test_ndjson_arbitrary_boundaries_unicode_blank_lines_and_final_text() -> None:
    async def scenario() -> None:
        wire = (
            '\n{"model":"demo","response":"hé","done":false}\r\n'
            '{"model":"demo","thinking":"hmm","done":false}\n'
            '{"model":"demo","response":"!","done":true,"eval_count":2}'
        ).encode()
        stream = ByteStream([wire[index : index + 1] for index in range(len(wire))])

        def handler(request: httpx.Request) -> httpx.Response:
            assert json.loads(request.content)["stream"] is True
            return httpx.Response(200, stream=stream)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            events = [event async for event in OllamaEngine(client=client).stream_generate(REQUEST)]
            assert [event.text for event in events] == ["hé", "", "!"]
            assert events[1].thinking == "hmm"
            assert events[-1].done and events[-1].metadata.eval_count == 2
            assert events[0].metadata.total_duration_ns is None
            assert stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body, error",
    [
        (b"not-json\n", EngineResponseError),
        (b"[]\n", EngineResponseError),
        (b'{"model":"demo","done":false}\n', EngineResponseError),
        (b"", EngineResponseError),
        (b'{"error":"private server details"}\n', EngineRemoteError),
        (b'{"model":"demo","done":false}\n{"error":"private"}\n', EngineRemoteError),
        (b'{"model":"demo","done":1}\n', EngineResponseError),
    ],
)
def test_stream_failures_are_typed_and_close_response(
    body: bytes, error: type[EngineError]
) -> None:
    async def scenario() -> None:
        stream = ByteStream([body])
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            with pytest.raises(error) as caught:
                async for _ in OllamaEngine(client=client).stream_generate(REQUEST):
                    pass
            assert "private" not in str(caught.value)
            assert stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "status, error",
    [
        (404, ModelNotFoundError),
        (429, EngineHTTPError),
        (500, EngineHTTPError),
        (302, EngineHTTPError),
    ],
)
@pytest.mark.parametrize("streaming", [False, True])
def test_http_errors_never_retry_or_follow_redirects(
    status: int, error: type[EngineHTTPError], streaming: bool
) -> None:
    async def scenario() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            assert request.url.path == "/api/generate"
            return httpx.Response(
                status,
                headers={"location": "https://example.com"},
                json={"error": "private prompt"},
            )

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), follow_redirects=True
        ) as client:
            engine = OllamaEngine(client=client)
            with pytest.raises(error) as caught:
                if streaming:
                    async for _ in engine.stream_generate(REQUEST):
                        pass
                else:
                    await engine.generate(REQUEST)
            assert caught.value.status_code == status and calls == 1
            assert "private" not in str(caught.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "exception, error",
    [
        (httpx.ConnectTimeout, EngineTimeoutError),
        (httpx.ReadTimeout, EngineTimeoutError),
        (httpx.WriteTimeout, EngineTimeoutError),
        (httpx.PoolTimeout, EngineTimeoutError),
        (httpx.ConnectError, EngineConnectionError),
        (httpx.RemoteProtocolError, EngineConnectionError),
    ],
)
@pytest.mark.parametrize("streaming", [False, True])
def test_transport_error_mapping(
    exception: type[httpx.RequestError], error: type[EngineError], streaming: bool
) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise exception("private request details", request=request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            engine = OllamaEngine(client=client)
            with pytest.raises(error) as caught:
                if streaming:
                    async for _ in engine.stream_generate(REQUEST):
                        pass
                else:
                    await engine.health_check()
            assert "private" not in str(caught.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field",
    [
        "total_duration",
        "load_duration",
        "prompt_eval_duration",
        "eval_duration",
        "eval_count",
        "prompt_eval_count",
    ],
)
@pytest.mark.parametrize("invalid", [-1, True, 1.5, "123"])
def test_invalid_metadata_is_not_coerced(field: str, invalid: object) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={**FINAL, field: invalid})
            )
        ) as client:
            with pytest.raises(EngineResponseError):
                await OllamaEngine(client=client).generate(REQUEST)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "body",
    [
        b"bad json",
        b"[]",
        b'{"model":"demo","done":false}',
        b'{"model":"demo"}',
        b'{"model":"demo","done":true,"response":5}',
    ],
)
def test_invalid_nonstream_response(body: bytes) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body))
        ) as client:
            with pytest.raises(EngineResponseError):
                await OllamaEngine(client=client).generate(REQUEST)

    asyncio.run(scenario())


def test_cancellation_propagates_and_closes_active_stream() -> None:
    async def scenario() -> None:
        stream = ByteStream([b'{"model":"demo","done":false}\n'], block=True)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:

            async def consume() -> None:
                async for _ in OllamaEngine(client=client).stream_generate(REQUEST):
                    pass

            task = asyncio.create_task(consume())
            await asyncio.wait_for(stream.waiting.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stream.closed
            assert not client.is_closed

    asyncio.run(scenario())


def test_early_exit_closes_stream_with_aclosing() -> None:
    async def scenario() -> None:
        stream = ByteStream([b'{"model":"demo","done":false}\n'], block=True)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            async with aclosing(OllamaEngine(client=client).stream_generate(REQUEST)) as events:
                async for _ in events:
                    break
            assert stream.closed

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "url",
    [
        "https://ollama.com",
        "http://192.168.0.2:11434",
        "http://localhost/api",
        "http://user:password@localhost",
        "http://localhost/?secret=x",
        "http://localhost/#x",
    ],
)
def test_reject_nonlocal_or_credentialed_configuration(url: str) -> None:
    with pytest.raises(ValueError):
        OllamaEngine(url)


@pytest.mark.parametrize(
    "timeout",
    [
        httpx.Timeout(None),
        httpx.Timeout(0),
        httpx.Timeout(float("inf")),
        httpx.Timeout(float("nan")),
    ],
)
def test_timeouts_must_be_finite(timeout: httpx.Timeout) -> None:
    with pytest.raises(ValueError):
        OllamaEngine(timeout=timeout)


def test_owned_client_context_manager() -> None:
    async def scenario() -> None:
        async with OllamaEngine() as engine:
            pass
        # A closed owned client fails before attempting any socket operation.
        with pytest.raises(RuntimeError, match="closed"):
            await engine.health_check()

    asyncio.run(scenario())


@pytest.mark.parametrize("streaming", [False, True])
def test_body_timeout_closes_response_after_headers(streaming: bool) -> None:
    async def scenario() -> None:
        stream = ByteStream(
            [b'{"model":"demo","done":false}\n'] if streaming else [],
            failure=httpx.ReadTimeout("private details"),
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            engine = OllamaEngine(client=client)
            with pytest.raises(EngineTimeoutError):
                if streaming:
                    async for _ in engine.stream_generate(REQUEST):
                        pass
                else:
                    await engine.generate(REQUEST)
            assert stream.closed

    asyncio.run(scenario())


def test_generate_cancellation_during_body_read() -> None:
    async def scenario() -> None:
        stream = ByteStream([], block=True)
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
        ) as client:
            task = asyncio.create_task(OllamaEngine(client=client).generate(REQUEST))
            await asyncio.wait_for(stream.waiting.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert stream.closed

    asyncio.run(scenario())


def test_model_missing_and_health_404_have_distinct_errors() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(404))
        ) as client:
            engine = OllamaEngine(client=client)
            with pytest.raises(ModelNotFoundError):
                await engine.model_info(REQUEST.model)
            with pytest.raises(EngineHTTPError) as caught:
                await engine.health_check()
            assert type(caught.value) is EngineHTTPError

    asyncio.run(scenario())


def test_custom_timeouts_and_optional_metadata() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.extensions["timeout"] == {"connect": 1, "read": 2, "write": 3, "pool": 4}
            return httpx.Response(
                200,
                json={"model": "demo", "done": True, "eval_duration": None, "future_field": 123},
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            engine = OllamaEngine(
                client=client, timeout=httpx.Timeout(connect=1, read=2, write=3, pool=4)
            )
            result = await engine.generate(REQUEST)
            assert result.metadata.eval_duration_ns is None
            assert result.metadata.eval_count is None

    asyncio.run(scenario())
