"""llama-server-specific HTTP fixtures, complementing shared adapter parity tests."""

import asyncio
import json
from typing import Any

import httpx
import pytest

from inferlab_core.engines import (
    EngineHTTPError,
    EngineResponseError,
    GenerationRequest,
    LlamaCppEngine,
    LlamaServerConfig,
    ModelNotFoundError,
)

CONFIG = LlamaServerConfig(model_alias="local-demo", gpu_layers=12, context_tokens=2048)
REQUEST = GenerationRequest(model=CONFIG.model_alias, prompt="Hello", max_tokens=8)
FINAL: dict[str, Any] = {
    "model": CONFIG.model_alias,
    "content": "Hi",
    "stop": True,
    "stop_type": "eos",
    "tokens_evaluated": 3,
    "timings": {"predicted_n": 2, "prompt_ms": 0, "predicted_ms": 1.25},
    "generation_settings": {"n_ctx": 2048},
}


def test_startup_arguments_are_values_only() -> None:
    assert CONFIG.startup_arguments() == (
        "--alias",
        "local-demo",
        "--gpu-layers",
        "12",
        "--ctx-size",
        "2048",
        "--parallel",
        "1",
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_alias", "../../file.gguf"),
        ("model_alias", "x; run-command"),
        ("model_alias", "https://example.com/model"),
        ("model_alias", ""),
        ("gpu_layers", True),
        ("gpu_layers", -1),
        ("gpu_layers", 201),
        ("context_tokens", True),
        ("context_tokens", 127),
        ("context_tokens", 8193),
    ],
)
def test_invalid_startup_config_rejected(field: str, value: Any) -> None:
    values: dict[str, Any] = {"model_alias": "local-demo", field: value}
    with pytest.raises(ValueError):
        LlamaServerConfig(**values)


def test_health_context_build_and_allowlisted_model_metadata() -> None:
    async def scenario() -> None:
        paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            paths.append(request.url.path)
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/props":
                return httpx.Response(
                    200,
                    json={
                        "build_info": "fixture-build",
                        "total_slots": 1,
                        "is_sleeping": False,
                        "default_generation_settings": {"n_ctx": 2048},
                        "model_path": "private/model.gguf",
                        "chat_template": "private template",
                    },
                )
            assert request.url.path == "/v1/models"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "local-demo",
                            "meta": {"n_params": 1234},
                            "path": "private/model.gguf",
                            "owned_by": "private username",
                        }
                    ]
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            engine = LlamaCppEngine(CONFIG, client=client)
            assert (await engine.health_check()).version == "fixture-build"
            info = await engine.model_info("local-demo")
            assert info.model == "local-demo" and info.parameter_size == "1234"
            assert info.quantization_level is None and info.family is None
            assert "private" not in repr(info)
        assert paths == ["/health", "/props", "/v1/models"]

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "field,value",
    [
        ("stop", 1),
        ("model", "different"),
        ("content", 123),
        ("tokens_evaluated", -1),
        ("tokens_evaluated", True),
        ("timings", {"predicted_n": True}),
        ("timings", {"predicted_n": -1}),
        ("timings", {"predicted_ms": -1}),
        ("timings", {"prompt_ms": "123"}),
        ("timings", {"predicted_ms": True}),
        ("timings", {"prompt_ms": None, "predicted_ms": float("nan")}),
        ("timings", {"predicted_ms": float("inf")}),
        ("generation_settings", {"n_ctx": 4096}),
    ],
)
def test_malformed_generation_metadata(field: str, value: Any) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=json.dumps({**FINAL, field: value}))
            )
        ) as client:
            with pytest.raises(EngineResponseError):
                await LlamaCppEngine(CONFIG, client=client).generate(REQUEST)

    asyncio.run(scenario())


def test_zero_and_missing_metadata_and_unit_conversion() -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=FINAL))
        ) as client:
            result = await LlamaCppEngine(CONFIG, client=client).generate(REQUEST)
            assert result.metadata.prompt_eval_duration_ns == 0
            assert result.metadata.eval_duration_ns == 1_250_000
            assert result.metadata.total_duration_ns is None
            assert result.metadata.load_duration_ns is None
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"model": "local-demo", "stop": True})
            )
        ) as client:
            result = await LlamaCppEngine(CONFIG, client=client).generate(REQUEST)
            assert result.metadata.eval_count is None and result.metadata.prompt_eval_count is None

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "wire",
    [
        b'data: {"model":"local-demo","stop":true}',
        b"data: [DONE]\n\n",
        b"data: []\n\n",
        b'data: {"stop":false}\n\n',
        b'data: {"model":"local-demo","stop":true,"content":null}\n\n',
    ],
)
def test_incomplete_or_invalid_sse(wire: bytes) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=wire))
        ) as client:
            with pytest.raises(EngineResponseError):
                async for _ in LlamaCppEngine(CONFIG, client=client).stream_generate(REQUEST):
                    pass

    asyncio.run(scenario())


def test_sse_comments_bom_metadata_and_multiline_data() -> None:
    async def scenario() -> None:
        wire = (
            "\ufeff: comment\r\nretry: 1000\r\nevent: message\r\nid: one\r\n"
            'data: {"content":"Hi",\r\ndata: "stop":false}\r\n\r\n'
            'data: {"model":"local-demo","stop":true}\n\n'
        ).encode()
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, content=wire))
        ) as client:
            events = [
                event
                async for event in LlamaCppEngine(CONFIG, client=client).stream_generate(REQUEST)
            ]
            assert [event.text for event in events] == ["Hi", ""] and events[-1].done

    asyncio.run(scenario())


def test_unknown_model_and_oversized_output_do_not_send_requests() -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            pytest.fail("Invalid model/configuration must not reach server")

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            engine = LlamaCppEngine(CONFIG, client=client)
            with pytest.raises(ModelNotFoundError):
                await engine.generate(GenerationRequest(model="unknown", prompt="Hello"))
            with pytest.raises(ModelNotFoundError):
                await engine.model_info("unknown")
            with pytest.raises(ValueError, match="max_tokens"):
                GenerationRequest(model="local-demo", prompt="", max_tokens=2049)
            small_context = LlamaCppEngine(
                LlamaServerConfig(model_alias="local-demo", context_tokens=1024),
                client=client,
            )
            with pytest.raises(ValueError, match="context"):
                await small_context.generate(
                    GenerationRequest(model="local-demo", prompt="", max_tokens=1500)
                )

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "props",
    [
        {"n_ctx": 4096, "slots": 1, "sleeping": False},
        {"n_ctx": 2048, "slots": 2, "sleeping": False},
        {"n_ctx": 2048, "slots": 1, "sleeping": True},
    ],
)
def test_health_rejects_mismatched_server_settings(props: dict[str, Any]) -> None:
    async def scenario() -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"status": "ok"}
                if request.url.path == "/health"
                else {
                    "default_generation_settings": {"n_ctx": props["n_ctx"]},
                    "total_slots": props["slots"],
                    "is_sleeping": props["sleeping"],
                    "build_info": "demo",
                },
            )

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(EngineResponseError):
                await LlamaCppEngine(CONFIG, client=client).health_check()

    asyncio.run(scenario())


def test_loading_is_503_not_ready_and_never_retries() -> None:
    async def scenario() -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(503, json={"error": {"message": "Loading private/model.gguf"}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(EngineHTTPError) as caught:
                await LlamaCppEngine(CONFIG, client=client).health_check()
            assert caught.value.status_code == 503 and calls == 1
            assert "private" not in str(caught.value)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "entries,error",
    [
        ([], ModelNotFoundError),
        ([{"id": "other"}], ModelNotFoundError),
        ([{"id": "local-demo"}, {"id": "other"}], EngineResponseError),
        (None, EngineResponseError),
        ([{"id": "local-demo", "meta": {"n_params": True}}], EngineResponseError),
    ],
)
def test_model_inventory_errors(entries: Any, error: type[Exception]) -> None:
    async def scenario() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"data": entries})
            )
        ) as client:
            with pytest.raises(error):
                await LlamaCppEngine(CONFIG, client=client).model_info("local-demo")

    asyncio.run(scenario())
