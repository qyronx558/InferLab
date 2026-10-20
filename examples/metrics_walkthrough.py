"""CPU-only teaching examples with invented data, never real benchmark results.

Run from the repository root: uv run --locked python examples/metrics_walkthrough.py
"""

from inferlab_core.benchmarking.metrics import (
    elapsed_ms,
    end_to_end_output_tps,
    estimate_dense_kv_bytes,
    mean_tpot_ms,
    observed_decode_tps,
    ttft_ms,
)


def main() -> None:
    print("SYNTHETIC TEACHING DATA - no model, GPU or measured performance")
    # A lookup table stands in for a model. This is not an inference adapter.
    next_token = {(10,): 20, (10, 20): 30, (10, 20, 30): 99}
    prompt = [10]
    context = prompt.copy()
    generated: list[int] = []
    for _ in range(5):
        token = next_token[tuple(context)]
        context.append(token)
        generated.append(token)
        if token == 99:
            break
    print("Toy autoregressive output:", generated, "original prompt:", prompt)

    start = 1_000_000_000
    arrivals = [1_120_000_000, 1_140_000_000, 1_180_000_000]
    end = 1_200_000_000
    print("TTFT (ms):", ttft_ms(start, arrivals[0]))
    print("Request latency (ms):", elapsed_ms(start, end))
    print("Mean TPOT (ms/token):", mean_tpot_ms(arrivals))
    print("Observed decode rate (tok/s):", observed_decode_tps(arrivals))
    print("End-to-end output rate (tok/s):", end_to_end_output_tps(3, end - start))
    cache_bytes = estimate_dense_kv_bytes(
        batch_size=1,
        layers=32,
        kv_heads=8,
        head_dim=128,
        cached_tokens=1024,
        bytes_per_element=2,
    )
    print("Estimated dense KV storage:", cache_bytes, "bytes =", cache_bytes / 2**20, "MiB")
    print("Idealized 3B weight payload: FP16 = 6,000,000,000 bytes; 4-bit = 1,500,000,000")
    print("Weight estimates exclude quantization metadata, KV cache and runtime overhead.")


if __name__ == "__main__":
    main()
