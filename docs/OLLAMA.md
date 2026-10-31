# Ollama transport

`inferlab_core.engines.EngineProtocol` is the async transport boundary. The
`OllamaEngine` implementation uses HTTPX and only contacts a configured loopback
origin (default `http://127.0.0.1:11434`). It is a library adapter, not a public
endpoint or a worker runner. API routes, dashboard fixtures and run schemas are
unchanged.

| Method | HTTP request | Result |
| --- | --- | --- |
| `generate(request)` | `POST /api/generate`, `stream: false` | Complete `GenerationResult` |
| `stream_generate(request)` | `POST /api/generate`, `stream: true` | Async generator of `GenerationResult` events, including the final event |
| `health_check()` | `GET /api/version` | `EngineHealth(version=...)`; failures raise typed errors |
| `model_info(model)` | `POST /api/show` | `ModelInfo` with format, family, size, quantization and capabilities |
| `aclose()` | None | Closes an adapter-owned HTTP client |

`GenerationRequest` takes an installed model name, prompt and
`max_tokens` from 1 to 2048 (default 128, mapped to `options.num_predict`). Model
names are sent
as JSON, never interpreted as commands or URL paths. Other generation settings,
chat, embeddings, images and model management are outside this minimal adapter.
Ollama must already be running and the model must already be installed. There is
no pull, retry, CLI execution or fallback to a remote service.

## Results and timing boundary

`GenerationResult` holds `model`, `text`, optional separate `thinking`, `done`,
`done_reason` and `GenerationMetadata`. Ollama's integer `total_duration`,
`load_duration`, `prompt_eval_duration` and `eval_duration` are preserved exactly
in the corresponding `*_ns` fields. Token counts are integers. Missing or null
measurements remain `None`; zero is preserved. Negative, boolean, fractional or
string measurements raise `EngineResponseError`. Unknown wire fields are ignored.

These are server-reported values, not client-observed benchmark results. A stream
event may contain multiple tokens, empty text, thinking only, or final text. NDJSON
parsing supports split network chunks, UTF-8 characters, blank lines, CRLF and a
final line without a newline. EOF before `done: true` is an error.

**TODO(owner):** record monotonic request/content/completion timestamps; decide
which events count as content; implement the benchmark runner's TTFT, TPOT,
throughput, warmups and aggregation. No clocks or benchmark calculations are added
here, and existing metric helpers are not called by the adapter.

## Timeouts, errors and cancellation

The default connect/read/write/pool limits are **5/60/10/5 seconds**. Pass an
`httpx.Timeout` to override them; every limit must be finite and positive. Read
timeouts limit inactivity between reads, not total experiment runtime. The future
runner owns overall deadlines (for example `asyncio.timeout`).

All transport failures derive from `EngineError`:

- `EngineTimeoutError`: HTTPX connect/read/write/pool timeout.
- `EngineConnectionError`: other HTTPX request/stream transport failures.
- `ModelNotFoundError`: HTTP 404 on generate or model-info requests; no download.
- `EngineHTTPError`: other unsuccessful HTTP responses, including redirects;
  exposes `status_code`. A health endpoint's 404 is this error.
- `EngineRemoteError`: Ollama's JSON `error` object, including mid-stream errors.
- `EngineResponseError`: malformed JSON/fields or missing stream completion.

Errors omit server bodies, prompts and local paths. Model metadata is allowlisted;
raw modelfiles and internal paths are not exposed. A health success indicates
reachability/version only, not GPU readiness or model availability. Offline workers
can catch `EngineConnectionError` or `EngineTimeoutError`; this library does not
change job state or poll/retry on its own.

Cancel the consuming asyncio task to cancel an in-flight request. Native
`asyncio.CancelledError` propagates, and active stream responses close. Always use
`contextlib.aclosing` around the stream, particularly when breaking early or doing
awaited work between events. Closing the connection does not guarantee immediate
server/GPU preemption; there is no invented server cancellation endpoint.

Use `async with OllamaEngine()` to close owned resources. Injected
`httpx.AsyncClient` instances remain caller-owned and must be closed by the caller.
Explicit timeouts and disabled redirects apply even with injected clients. The
default client disables environment proxies; injected clients are trusted test or
operator configuration and must be configured accordingly. Loopback validation is
not an authentication boundary: keep Ollama private, use locally installed models,
and disable Ollama cloud features in the local server configuration when required.

## Local usage and verification

After `uv sync --locked`, use this Python example in a local script. Replace the
model name with an **already installed local model** before running it with
`uv run --locked python path/to/script.py`. It deliberately performs generation
only when you run the script.

```python
import asyncio
from contextlib import aclosing

from inferlab_core.engines import GenerationRequest, OllamaEngine


async def main() -> None:
    async with OllamaEngine() as engine:
        print(await engine.health_check())
        model = "YOUR_INSTALLED_LOCAL_MODEL"
        print(await engine.model_info(model))
        request = GenerationRequest(model=model, prompt="Say hello.", max_tokens=16)
        print((await engine.generate(request)).text)
        async with aclosing(engine.stream_generate(request)) as events:
            async for event in events:
                print(event.text, end="", flush=True)
        print()


asyncio.run(main())
```

CPU-only mock tests require no Ollama process or model:

```powershell
uv run --locked pytest tests/test_ollama.py
```

Tests cover request shape, protocol conformance, nanosecond preservation, optional
metadata, NDJSON boundaries, malformed/truncated responses, HTTP/inline errors,
timeouts, redirects, task cancellation, early exit and client ownership. A live
small-model smoke test remains a manual release gate; mock tests do not establish
real model/GPU integration or benchmark correctness.

## Official references

- [Ollama generate](https://docs.ollama.com/api/generate)
- [Ollama streaming](https://docs.ollama.com/api/streaming)
- [Ollama model details](https://docs.ollama.com/api-reference/show-model-details)
- [Ollama version](https://docs.ollama.com/api-reference/get-version)
- [Ollama errors](https://docs.ollama.com/api/errors)
- [HTTPX async streaming and closure](https://www.python-httpx.org/async/)
- [HTTPX timeout semantics](https://www.python-httpx.org/advanced/timeouts/)
