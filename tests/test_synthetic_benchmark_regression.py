"""Golden regression for deterministic synthetic metric derivation.

These timelines are fixed CPU fixtures, not engine measurements. A future runner
must preserve the same units, zero/unavailable distinctions and clock handling.
"""

from dataclasses import dataclass
from typing import Any

import pytest

from inferlab_core.benchmarking.metrics import (
    elapsed_ms,
    end_to_end_output_tps,
    estimate_dense_kv_bytes,
    mean_tpot_ms,
    observed_decode_tps,
    ttft_ms,
)


@dataclass(frozen=True)
class Observation:
    start_ns: int
    first_content_ns: int | None
    arrivals_ns: list[int]
    end_ns: int
    output_tokens: int


def derive(observation: Observation) -> dict[str, Any]:
    arrivals = observation.arrivals_ns
    return {
        "ttft_ms": ttft_ms(observation.start_ns, observation.first_content_ns),
        "request_latency_ms": elapsed_ms(observation.start_ns, observation.end_ns),
        "mean_tpot_ms": mean_tpot_ms(arrivals),
        "observed_decode_tps": observed_decode_tps(arrivals),
        "end_to_end_output_tps": end_to_end_output_tps(
            observation.output_tokens, observation.end_ns - observation.start_ns
        ),
        "arrivals_ns": list(arrivals),
    }


CASES: dict[str, tuple[Observation, dict[str, float | None]]] = {
    "steady": (
        Observation(
            1_000_000_000,
            1_120_000_000,
            [1_120_000_000, 1_140_000_000, 1_180_000_000],
            1_200_000_000,
            3,
        ),
        {
            "ttft_ms": 120.0,
            "request_latency_ms": 200.0,
            "mean_tpot_ms": 30.0,
            "observed_decode_tps": 33.333333333333336,
            "end_to_end_output_tps": 15.0,
        },
    ),
    "single_token": (
        Observation(0, 2_000_000, [2_000_000], 10_000_000, 1),
        {
            "ttft_ms": 2.0,
            "request_latency_ms": 10.0,
            "mean_tpot_ms": None,
            "observed_decode_tps": None,
            "end_to_end_output_tps": 100.0,
        },
    ),
    "no_content": (
        Observation(0, None, [], 10_000_000, 0),
        {
            "ttft_ms": None,
            "request_latency_ms": 10.0,
            "mean_tpot_ms": None,
            "observed_decode_tps": None,
            "end_to_end_output_tps": 0.0,
        },
    ),
    "zero_duration": (
        Observation(5, 5, [5, 5, 5], 5, 3),
        {
            "ttft_ms": 0.0,
            "request_latency_ms": 0.0,
            "mean_tpot_ms": 0.0,
            "observed_decode_tps": None,
            "end_to_end_output_tps": None,
        },
    ),
    "large_clock_origin": (
        Observation(
            10**18,
            10**18 + 2_500_000,
            [10**18 + 2_500_000, 10**18 + 4_500_000, 10**18 + 8_500_000],
            10**18 + 12_500_000,
            3,
        ),
        {
            "ttft_ms": 2.5,
            "request_latency_ms": 12.5,
            "mean_tpot_ms": 3.0,
            "observed_decode_tps": 333.3333333333333,
            "end_to_end_output_tps": 240.0,
        },
    ),
}


@pytest.mark.parametrize("name", list(CASES))
def test_synthetic_timeline_metrics_match_golden_values(name: str) -> None:
    observation, expected = CASES[name]
    result = derive(observation)
    for key, value in expected.items():
        assert result[key] == pytest.approx(value)
    assert result["arrivals_ns"] == observation.arrivals_ns


def test_synthetic_timeline_derivation_is_deterministic_and_input_preserving() -> None:
    observation, _ = CASES["steady"]
    first = derive(observation)
    second = derive(observation)
    assert first == second
    assert observation.arrivals_ns == [1_120_000_000, 1_140_000_000, 1_180_000_000]


def test_synthetic_kv_estimate_is_stable_for_fixed_shape() -> None:
    shape = {
        "batch_size": 1,
        "layers": 32,
        "kv_heads": 8,
        "head_dim": 128,
        "cached_tokens": 1024,
        "bytes_per_element": 2,
    }
    assert estimate_dense_kv_bytes(**shape) == 134_217_728
    assert estimate_dense_kv_bytes(**{**shape, "cached_tokens": 0}) == 0
