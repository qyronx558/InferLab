# Local llama-server transport

`inferlab_core.engines.LlamaCppEngine` implements the same async `EngineProtocol`
and dataclass results/errors as `OllamaEngine`. It connects to an existing local,
single-model llama-server. There is no binary discovery, download, subprocess,
shell execution, model management, runner or public execution endpoint. Existing
dashboard data remains DEMO DATA. Timing and benchmark calculations remain owner
TODOs outside the transport.

## Configure and launch manually

Use your already installed binary and GGUF model. In a separate PowerShell
terminal, adjust these example paths and launch the server yourself:

```powershell
& 'C:\local\llama.cpp\llama-server.exe' `
  --model 'C:\local\models\your-model.gguf' `
  --alias local-demo --host 127.0.0.1 --port 8080 `
  --gpu-layers 12 --ctx-size 2048 --parallel 1 --offline
```

This is documentation for an operator command, not a command executed by InferLab.
Use a CUDA-capable binary if GPU offload is wanted; zero GPU layers requests CPU
layers. Actual memory placement must be checked in your local server diagnostics.
Do not use repository/download arguments or router mode for this adapter.

```python
from inferlab_core.engines import LlamaCppEngine, LlamaServerConfig

config = LlamaServerConfig(
    model_alias="local-demo", gpu_layers=12, context_tokens=2048
)
engine = LlamaCppEngine(config, base_url="http://127.0.0.1:8080")
```

`config.startup_arguments()` returns a tuple of alias/GPU-layer/context/parallel
flag values for manual operator use. It never executes them. Config rejects unsafe
alias syntax, non-integer/boolean limits, GPU layers outside 0-200 and context
outside 128-8192, consistent with the MVP's bounds. To change these settings,
restart the server manually with matching flags; creating an adapter does not
reconfigure a running server. GPU layers are declared startup intent, not verified
observations. There is no documented HTTP GPU-layer setter used here.

## HTTP and shared types

| Protocol method | HTTP API | Behavior |
| --- | --- | --- |
| `generate` | `POST /completion`, `stream: false` | Native text completion mapped to `GenerationResult`. |
| `stream_generate` | `POST /completion`, `stream: true` | SSE frames mapped to shared events, including final content/metadata. |
| `health_check` | `GET /health`, then `GET /props` | Requires ready status, matching per-slot context and exactly one slot; rejects sleeping state when reported. Returns `EngineHealth.version` from `build_info`. |
| `model_info` | `GET /v1/models` | Requires one model matching the configured alias; returns allowlisted metadata only. |

Requests map `max_tokens` to `n_predict` and explicitly disable prompt caching via
`cache_prompt: false`. No GPU-layer or invented per-request context setting is sent
over HTTP. Call `health_check` and `model_info` before benchmark observation, outside
the future runner's timed boundary. Generation also checks the returned alias and,
when present, `generation_settings.n_ctx`. A missing context echo does not verify
context; preflight and operator controls remain necessary. Preflight is not atomic
with generation and cannot prevent an external process from changing/restarting
the server.

`content` becomes `text`, `stop` becomes `done`, and the native `stop_type` is
preserved as `done_reason`. Native streaming can omit model metadata on partial
events; the final response must identify the configured alias. SSE handles CRLF,
comments, multi-line data fields, split network chunks and UTF-8. A valid final
`stop: true` event is required: an early EOF, unfinished SSE frame or bare
`[DONE]` sentinel is not native completion evidence.

`tokens_evaluated` becomes the server-reported input count; `timings.predicted_n`
becomes the output count. Neither is inferred from chunks or characters. Server
`prompt_ms` and `predicted_ms` undergo unit conversion into shared nanosecond
duration fields; this does not provide nanosecond measurement precision.
Sub-nanosecond fractions are truncated. No total duration, loading duration,
TTFT, TPOT or throughput is synthesized. Missing metadata remains `None`, while
zero is preserved. Invalid/negative/nonfinite measurements raise typed errors.

`ModelInfo.parameter_size` is the exact decimal parameter-count string from
`meta.n_params`, when available. Unsupported family, format, quantization and
capability metadata remain unset/empty; the adapter does not infer them from model
filenames or expose raw model paths, owner names, templates or server properties.
Identity/checksum and effective GPU settings still require independent provenance
verification before a benchmark report can claim reproducibility.

## Ownership, cancellation and error parity

Use `async with` for an owned client, and `contextlib.aclosing` when consuming a
stream, especially when breaking early:

```python
import asyncio
from contextlib import aclosing

from inferlab_core.engines import GenerationRequest, LlamaCppEngine, LlamaServerConfig


async def main() -> None:
    config = LlamaServerConfig("local-demo", gpu_layers=12, context_tokens=2048)
    async with LlamaCppEngine(config) as engine:
        print(await engine.health_check())
        print(await engine.model_info(config.model_alias))
        request = GenerationRequest(config.model_alias, "Say hello.", max_tokens=16)
        async with aclosing(engine.stream_generate(request)) as events:
            async for event in events:
                print(event.text, end="", flush=True)


asyncio.run(main())
```

Save the complete example as a local script and run it explicitly with
`uv run --locked python path/to/script.py` after manual server startup.

Both transports use the same loopback-only origin validation, no redirects or
retries, owned-client proxy policy and finite connect/read/write/pool timeouts
(defaults 5/60/10/5 seconds). An injected HTTPX client remains caller-owned and
trusted operator configuration. Read timeouts bound inactivity; the future runner
owns total experiment deadlines.

The shared exceptions are `EngineTimeoutError`, `EngineConnectionError`,
`EngineHTTPError`, `ModelNotFoundError`, `EngineRemoteError` and
`EngineResponseError`; bodies and private paths are omitted from exception text.
Loading/unavailable HTTP 503 is an `EngineHTTPError`, not a ready result. Model
404/missing configured alias is `ModelNotFoundError`; inline engine errors are
`EngineRemoteError`. Native asyncio cancellation propagates and active responses
close. HTTP closure does not prove immediate server/GPU termination; the future
worker must confirm stop before scheduling more work.

## Verification and limits

```powershell
uv run --locked pytest tests/test_engine_parity.py tests/test_llama_cpp.py tests/test_ollama.py
```

CPU-only mocks exercise the same protocol behavior for both adapters: typed
generation/health/model results, normalized metadata, streaming, HTTP/transport
failures, timeouts, cancellation, early closure and client ownership. Additional
llama-server cases check SSE framing and expected startup settings. No binary,
model, socket or GPU is needed in CI. Live small-model verification remains a
manual release gate; mocks do not establish compatibility with every build.

These adapters provide interface parity, not evidence of benchmark equivalence:
native completion uses a raw prompt, whereas Ollama may apply its model template.
Sampling, thinking, tokenization, caching and hardware conditions must be aligned
and recorded before comparing real results. Idle sleep/warmup behavior also needs
explicit operator control; this adapter does not reset cold/warm model state.

The target is the native single-model HTTP/SSE contract documented in the official
[llama-server README](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
(reviewed 2026-10-22). Record your installed build; incompatible response shapes
fail explicitly. For shared timeout/cancellation details, see the
[Ollama guide](OLLAMA.md) and [HTTPX async documentation](https://www.python-httpx.org/async/).
