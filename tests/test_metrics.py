"""Deterministic CPU tests for metric definitions, units and undefined cases."""

from collections.abc import Callable, Sequence
from typing import cast

import pytest

from inferlab_core.benchmarking.metrics import (
    elapsed_ms,
    end_to_end_output_tps,
    estimate_dense_kv_bytes,
    mean_tpot_ms,
    observed_decode_tps,
    ttft_ms,
)


def test_synthetic_timing_example() -> None:
    start = 1_000_000_000
    arrivals = [1_120_000_000, 1_140_000_000, 1_180_000_000]
    end = 1_200_000_000
    assert ttft_ms(start, arrivals[0]) == pytest.approx(120.0)
    assert elapsed_ms(start, end) == pytest.approx(200.0)
    assert mean_tpot_ms(arrivals) == pytest.approx(30.0)
    assert observed_decode_tps(arrivals) == pytest.approx(33.333333333333336)
    assert end_to_end_output_tps(3, end - start) == pytest.approx(15.0)


@pytest.mark.parametrize("origin", [-(10**30), -500, 0, 10**30])
def test_clock_origin_does_not_change_intervals(origin: int) -> None:
    assert elapsed_ms(origin, origin + 7) == pytest.approx(0.000007)
    assert ttft_ms(origin, origin + 1_000_000) == pytest.approx(1.0)
    arrivals = [origin, origin + 2_000_000, origin + 6_000_000]
    assert mean_tpot_ms(arrivals) == pytest.approx(3.0)
    assert observed_decode_tps(arrivals) == pytest.approx(333.3333333333333)


def test_uneven_intervals_and_two_token_boundary() -> None:
    assert mean_tpot_ms([0, 1_000_000, 10_000_000]) == pytest.approx(5.0)
    assert observed_decode_tps([0, 1_000_000, 10_000_000]) == pytest.approx(200.0)
    assert mean_tpot_ms([0, 2_000_000]) == pytest.approx(2.0)
    assert observed_decode_tps([0, 2_000_000]) == pytest.approx(500.0)


def test_missing_observations_and_real_zero_are_distinct() -> None:
    assert ttft_ms(0, None) is None
    assert ttft_ms(0, 0) == 0.0
    assert elapsed_ms(5, 5) == 0.0
    assert mean_tpot_ms([5, 5, 5]) == 0.0
    assert observed_decode_tps([5, 5, 5]) is None
    assert end_to_end_output_tps(0, 1) == 0.0
    assert end_to_end_output_tps(3, 0) is None
    assert end_to_end_output_tps(0, 0) is None


@pytest.mark.parametrize("arrivals", [[], [0], [-500]])
@pytest.mark.parametrize("metric", [mean_tpot_ms, observed_decode_tps])
def test_too_few_tokens_is_unavailable(
    metric: Callable[[Sequence[int]], float | None], arrivals: list[int]
) -> None:
    assert metric(arrivals) is None


@pytest.mark.parametrize("metric", [mean_tpot_ms, observed_decode_tps])
def test_ties_with_positive_span_and_input_preservation(
    metric: Callable[[Sequence[int]], float | None],
) -> None:
    arrivals = [0, 0, 2_000_000]
    original = arrivals.copy()
    expected = 1.0 if metric is mean_tpot_ms else 1000.0
    assert metric(arrivals) == pytest.approx(expected)
    assert arrivals == original
    assert metric(tuple(arrivals)) == pytest.approx(expected)


@pytest.mark.parametrize("bad", [True, False, 1.5, float("nan"), float("inf"), "1", None])
def test_scalar_types_are_not_coerced(bad: object) -> None:
    value = cast(int, bad)
    for start, end in [(value, 10), (0, value)]:
        with pytest.raises(TypeError):
            elapsed_ms(start, end)
    with pytest.raises(TypeError):
        ttft_ms(value, None)  # Validate start even when content is absent.
    if bad is not None:  # None is a supported first-content observation.
        with pytest.raises(TypeError):
            ttft_ms(0, value)
    with pytest.raises(TypeError):
        end_to_end_output_tps(value, 10)
    with pytest.raises(TypeError):
        end_to_end_output_tps(1, value)


@pytest.mark.parametrize(
    "bad",
    ["123", b"123", bytearray(b"123"), None, iter([1, 2]), [True], [1.0], [None], [0, 1, "2"]],
)
@pytest.mark.parametrize("metric", [mean_tpot_ms, observed_decode_tps])
def test_invalid_sequences_are_rejected_even_without_enough_samples(
    metric: Callable[[Sequence[int]], float | None], bad: object
) -> None:
    with pytest.raises(TypeError):
        metric(cast(Sequence[int], bad))


@pytest.mark.parametrize("metric", [mean_tpot_ms, observed_decode_tps])
def test_decreasing_token_timestamps_are_invalid(
    metric: Callable[[Sequence[int]], float | None],
) -> None:
    with pytest.raises(ValueError):
        metric([0, 3, 2])


def test_negative_durations_and_counts_are_invalid() -> None:
    with pytest.raises(ValueError):
        elapsed_ms(10, 9)
    with pytest.raises(ValueError):
        ttft_ms(10, 9)
    for tokens, duration in [(-1, 1), (1, -1), (-1, 0)]:
        with pytest.raises(ValueError):
            end_to_end_output_tps(tokens, duration)


KV_SHAPE = {
    "batch_size": 1,
    "layers": 32,
    "kv_heads": 8,
    "head_dim": 128,
    "cached_tokens": 1024,
    "bytes_per_element": 2,
}


def test_dense_kv_estimate_and_scaling() -> None:
    assert estimate_dense_kv_bytes(**KV_SHAPE) == 134_217_728
    for dimension in ["batch_size", "cached_tokens"]:
        shape = dict(KV_SHAPE)
        shape[dimension] *= 2
        assert estimate_dense_kv_bytes(**shape) == 268_435_456
    assert estimate_dense_kv_bytes(**{**KV_SHAPE, "cached_tokens": 0}) == 0
    assert estimate_dense_kv_bytes(**{**KV_SHAPE, "bytes_per_element": 1}) == 67_108_864


@pytest.mark.parametrize("dimension", list(KV_SHAPE))
@pytest.mark.parametrize("bad", [True, 1.5, "2", None])
def test_kv_dimensions_require_integers(dimension: str, bad: object) -> None:
    shape = dict(KV_SHAPE)
    shape[dimension] = cast(int, bad)
    with pytest.raises(TypeError):
        estimate_dense_kv_bytes(**shape)


@pytest.mark.parametrize("dimension", list(KV_SHAPE))
def test_invalid_kv_dimensions_are_checked_even_for_empty_cache(dimension: str) -> None:
    shape = {**KV_SHAPE, "cached_tokens": 0}
    shape[dimension] = -1 if dimension == "cached_tokens" else 0
    with pytest.raises(ValueError):
        estimate_dense_kv_bytes(**shape)
