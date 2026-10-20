# CPU-only metric helpers

Implemented at the owner's explicit request after the tutoring step. This code
was AI-assisted; it should not be described as a handwritten owner implementation.
The default learning boundary for later benchmark algorithms still applies.

`inferlab_core.benchmarking.metrics` contains six pure functions. It has no model,
GPU, clock-reading, network, file, queue or publishing dependency. Callers record
events; helpers calculate values. Existing demo reports remain synthetic and are
not recomputed or presented as measured results.

| Function | Definition / units |
| --- | --- |
| `elapsed_ms` | Ordered same-clock nanosecond difference, converted to milliseconds. |
| `ttft_ms` | Request start to first content-bearing stream event, in milliseconds. Missing content returns `None`. |
| `mean_tpot_ms` | First-to-last token duration divided by **N-1** intervals, in ms/token. |
| `observed_decode_tps` | **N-1** token intervals divided by their first-to-last elapsed seconds. |
| `end_to_end_output_tps` | All output tokens divided by the entire successful request duration. |
| `estimate_dense_kv_bytes` | `2 × batch × layers × KV heads × head dimension × cached tokens × bytes/element`. |

Two token events define one interval. TPOT and observed decode rate are unavailable
with fewer than two token events. Equal timestamps are allowed: all ties give zero
TPOT but an undefined decode rate (`None`). Zero request duration gives an undefined
end-to-end rate; zero output tokens over a positive duration gives zero.

Use integer `perf_counter_ns()` readings from the same clock. Absolute origins can
be negative or very large: subtraction happens before floating conversion. Wrong
types (including bools) raise `TypeError`; reversed event order, negative counts or
durations and invalid cache dimensions raise `ValueError`. All sequence elements
are checked even when there are too few samples. No input sequence is mutated.

The timestamp helpers need individual token events. Arbitrary streamed chunks can
contain multiple tokens; do not feed chunk timestamps into token-rate functions.
Ignore empty metadata events when finding first content, while preserving valid
whitespace output. TTFT includes loading/queuing/transport within the observed
interval and is not isolated prefill time. Engine evaluation timings are separate
measurements. Callers must separately retain failed/cancelled state and map missing
values to the wire contract's `null` plus an unavailable reason.

The KV helper estimates ordinary dense logical K+V storage, not peak GPU memory.
Use KV heads rather than query heads. Weights, activations, scratch buffers, cache
metadata/padding, reserved allocations and other processes need additional memory.
Sliding, offloaded, quantized or latent caches require their own accounting. An
8 GB GPU is not guaranteed to fit a model just because its weights fit; weight
quantization does not automatically change cache precision.

```powershell
uv run --locked pytest tests/test_metrics.py
uv run --locked python examples/metrics_walkthrough.py
uv run --locked ruff check .
uv run --locked mypy
```

The walkthrough implements the toy generation exercise and prints the invented
120 ms TTFT / 200 ms latency / 30 ms TPOT example. It also estimates 128 MiB of KV
storage and shows idealized FP16/four-bit weight payloads. None is a measurement.

Official references: [Python clocks](https://docs.python.org/3.12/library/time.html#time.perf_counter_ns),
[Hugging Face caching](https://huggingface.co/docs/transformers/main/en/cache_explanation),
[NVIDIA metric definitions](https://docs.nvidia.com/nim/benchmarking/llm/2.0.0/metrics),
[NVIDIA inference memory discussion](https://developer.nvidia.com/blog/mastering-llm-techniques-inference-optimization),
and [Ollama evaluation fields](https://docs.ollama.com/api/generate).
