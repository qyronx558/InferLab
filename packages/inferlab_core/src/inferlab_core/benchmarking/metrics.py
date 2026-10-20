"""Pure metric calculations from caller-recorded, same-clock nanosecond events.

Token timestamps must represent individual output tokens, not arbitrary network
chunks. Undefined measurements return None; malformed inputs raise TypeError or
ValueError. This module never reads clocks, performs I/O, or executes inference.
"""

from collections.abc import Sequence

_NS_PER_MS = 1_000_000
_NS_PER_SECOND = 1_000_000_000


def _require_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer, not a boolean or coerced value")
    return value


def _token_span(token_arrivals_ns: Sequence[int]) -> tuple[int, int] | None:
    if not isinstance(token_arrivals_ns, Sequence) or isinstance(
        token_arrivals_ns, (str, bytes, bytearray)
    ):
        raise TypeError("token_arrivals_ns must be a sequence of integer timestamps")
    # Snapshot without mutating the caller's sequence, then validate every event.
    timestamps = tuple(token_arrivals_ns)
    for timestamp in timestamps:
        _require_int(timestamp, "token timestamp")
    if any(later < earlier for earlier, later in zip(timestamps, timestamps[1:], strict=False)):
        raise ValueError("Token timestamps must be nondecreasing")
    if len(timestamps) < 2:
        return None
    return len(timestamps) - 1, timestamps[-1] - timestamps[0]


def elapsed_ms(start_ns: int, end_ns: int) -> float:
    """Convert an ordered same-clock interval to milliseconds; equal times yield 0."""
    _require_int(start_ns, "start_ns")
    _require_int(end_ns, "end_ns")
    if end_ns < start_ns:
        raise ValueError("end_ns must not precede start_ns")
    # Subtract integers before conversion to preserve small deltas at large origins.
    return (end_ns - start_ns) / _NS_PER_MS


def ttft_ms(request_start_ns: int, first_content_ns: int | None) -> float | None:
    """Client-observed time to first content; None means no content was observed.

    Includes any loading, queuing, prefill and transport inside these boundaries;
    it does not isolate engine prefill time. The start is validated even if content
    is missing. Whitespace can be content; empty metadata events are not content.
    """
    _require_int(request_start_ns, "request_start_ns")
    if first_content_ns is None:
        return None
    return elapsed_ms(request_start_ns, first_content_ns)


def mean_tpot_ms(token_arrivals_ns: Sequence[int]) -> float | None:
    """Mean observed milliseconds per interval after the first output token.

    N token events define N-1 intervals. Fewer than two events is unavailable;
    tied timestamps are permitted and an entirely tied sequence yields zero.
    """
    span = _token_span(token_arrivals_ns)
    if span is None:
        return None
    intervals, duration_ns = span
    return duration_ns / intervals / _NS_PER_MS


def observed_decode_tps(token_arrivals_ns: Sequence[int]) -> float | None:
    """Observed (N-1)/(last-first) token rate, excluding the first-token wait.

    This is not an engine-reported evaluation rate or aggregate multi-request
    throughput. A zero-duration observation has no defined finite rate.
    """
    span = _token_span(token_arrivals_ns)
    if span is None:
        return None
    intervals, duration_ns = span
    if duration_ns == 0:
        return None
    return intervals * _NS_PER_SECOND / duration_ns


def end_to_end_output_tps(output_tokens: int, request_latency_ns: int) -> float | None:
    """All output tokens divided by full successful request duration, in seconds.

    Zero tokens over a positive duration yields zero; a zero duration is
    unavailable. A caller must separately retain failed/cancelled request state.
    """
    _require_int(output_tokens, "output_tokens")
    _require_int(request_latency_ns, "request_latency_ns")
    if output_tokens < 0 or request_latency_ns < 0:
        raise ValueError("Token counts and request duration must be nonnegative")
    if request_latency_ns == 0:
        return None
    return output_tokens * _NS_PER_SECOND / request_latency_ns


def estimate_dense_kv_bytes(
    *,
    batch_size: int,
    layers: int,
    kv_heads: int,
    head_dim: int,
    cached_tokens: int,
    bytes_per_element: int,
) -> int:
    """Estimate logical dense K+V storage for equally sized sequences, in bytes.

    Uses KV heads, not query heads. Excludes weights, scratch space, allocation
    padding/metadata and runtime overhead. Not valid for compressed/latent caches
    or a claim of measured VRAM. Zero cached tokens needs zero logical storage.
    """
    dimensions = {
        "batch_size": batch_size,
        "layers": layers,
        "kv_heads": kv_heads,
        "head_dim": head_dim,
        "bytes_per_element": bytes_per_element,
    }
    for name, value in dimensions.items():
        _require_int(value, name)
        if value <= 0:
            raise ValueError(f"{name} must be positive")
    _require_int(cached_tokens, "cached_tokens")
    if cached_tokens < 0:
        raise ValueError("cached_tokens must be nonnegative")
    return 2 * batch_size * layers * kv_heads * head_dim * cached_tokens * bytes_per_element
