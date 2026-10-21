"""Reproducible config/result validation using synthetic YAML, without execution."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import ValidationError

from inferlab_api.contracts import (
    ExperimentConfig,
    ExperimentSubmitRequest,
    Registry,
    Result,
    validate_submission,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "experiments/fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load((FIXTURES / f"{name}.yaml").read_text("utf-8")))


@pytest.mark.parametrize("name", ["experiment-warm", "experiment-cold"])
def test_yaml_configs_round_trip_with_stable_ids(name: str) -> None:
    payload = load_fixture(name)
    config = ExperimentConfig.model_validate(payload)
    assert ExperimentConfig.model_validate_json(config.model_dump_json()) == config
    assert config.experiment_id == payload["experiment_id"]
    assert config.prompt_id == "synthetic-prompt-v1"
    if config.condition == "cold":
        assert config.warmups == 0 and config.sampling.seed is None


@pytest.mark.parametrize("state", ["complete", "failed", "cancelled"])
def test_yaml_results_round_trip_and_disclose_demo_data(state: str) -> None:
    result = Result.model_validate(load_fixture(f"result-{state}"))
    assert Result.model_validate_json(result.model_dump_json()) == result
    assert result.label == "DEMO DATA" and result.data_kind == "demo"
    assert result.run.state == state
    assert result.experiment_id == result.run.experiment_id == result.config.experiment_id
    assert result.run.recorded_at.utcoffset() is not None
    assert result.provenance.hardware.driver_version
    if state == "complete":
        assert not result.errors and result.run.input_tokens is not None
    else:
        assert result.errors[0].code == result.run.error_code
        assert result.run.input_tokens is None and result.run.output_tokens is None
        assert result.run.ttft.value is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("experiment_id", "../unsafe"),
        ("experiment_id", ""),
        ("model_revision", "https://example.com/model"),
        ("model_sha256", "a" * 63),
        ("model_sha256", "g" * 64),
        ("model_sha256", 123),
        ("engine_version", ""),
        ("engine_build", ""),
        ("quantization", "unknown"),
        ("prompt_id", "../private.txt"),
        ("seed_supported", "false"),
        ("gpu_device_id", "cuda:0; run-command"),
        ("gpu_layers", -1),
        ("gpu_layers", 201),
        ("gpu_layers", True),
        ("input_token_budget", 0),
        ("input_token_budget", "512"),
        ("warmups", -1),
        ("repetitions", 0),
        ("concurrency", 0),
        ("executable", "untrusted.exe"),
    ],
)
def test_config_rejects_invalid_identity_limits_and_extra_fields(field: str, value: object) -> None:
    payload = load_fixture("experiment-warm")
    payload[field] = value
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate(payload)


@pytest.mark.parametrize(
    "field,value",
    [
        ("temperature", -0.1),
        ("temperature", float("nan")),
        ("temperature", float("inf")),
        ("temperature", True),
        ("top_p", 0.0),
        ("top_p", 1.1),
        ("top_p", "1.0"),
        ("seed", -1),
        ("seed", True),
        ("seed", "42"),
        ("seed", 2147483648),
    ],
)
def test_sampling_values_are_finite_and_strict(field: str, value: object) -> None:
    payload = load_fixture("experiment-warm")
    payload["sampling"][field] = value
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate(payload)


def test_seed_requires_declared_and_resolved_capability() -> None:
    payload = load_fixture("experiment-warm")
    payload["seed_supported"] = False
    with pytest.raises(ValidationError, match="seed"):
        ExperimentConfig.model_validate(payload)
    payload["sampling"]["seed"] = None
    assert ExperimentConfig.model_validate(payload).sampling.seed is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("model_revision", "different-revision"),
        ("model_sha256", "f" * 64),
        ("quantization", "FP16"),
        ("engine_version", "different-version"),
        ("engine_build", "different-build"),
        ("prompt_id", "different-prompt"),
    ],
)
def test_registry_rejects_stale_pins(field: str, value: str) -> None:
    catalog = json.loads((ROOT / "contracts/fixtures/demo.json").read_text("utf-8"))
    request = deepcopy(catalog["submit_request"])
    request["config"][field] = value
    with pytest.raises(ValueError, match="provenance"):
        validate_submission(
            ExperimentSubmitRequest.model_validate(request),
            Registry.model_validate(catalog["registry"]["data"]),
        )


@pytest.mark.parametrize(
    "path,value",
    [
        (("experiment_id",), "EXP-other"),
        (("config", "experiment_id"), "EXP-other"),
        (("run", "experiment_id"), "EXP-other"),
        (("provenance", "model", "id"), "other-model"),
        (("provenance", "model", "revision"), "other-revision"),
        (("provenance", "model", "sha256"), "f" * 64),
        (("provenance", "model", "quantization"), "FP16"),
        (("provenance", "engine", "version"), "other-version"),
        (("provenance", "engine", "build"), "other-build"),
        (("provenance", "engine", "seed_supported"), False),
        (("provenance", "workload", "prompt_id"), "other-prompt"),
        (("provenance", "hardware", "gpu_device_id"), "gpu-1"),
        (("provenance", "hardware", "gpu_layers"), 2),
        (("provenance", "hardware", "driver_version"), ""),
        (("run", "condition"), "cold"),
        (("run", "repetition"), 20),
        (("run", "recorded_at"), "2026-10-22T10:00:00"),
        (("run", "input_tokens"), None),
        (("run", "input_tokens"), 8192),
        (("run", "output_tokens"), 2049),
        (("run", "output_tokens"), True),
        (("run", "ttft", "value"), 99999.0),
        (("label",), "MEASURED DATA"),
        (("local_path",), "private/trace"),
    ],
)
def test_result_rejects_inconsistent_or_unsafe_evidence(
    path: tuple[str, ...], value: object
) -> None:
    payload = load_fixture("result-complete")
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        Result.model_validate(payload)


def test_warmup_indices_use_the_warmup_limit() -> None:
    payload = load_fixture("result-complete")
    payload["run"].update(kind="warmup", repetition=payload["config"]["warmups"] - 1)
    Result.model_validate(payload)
    payload["run"]["repetition"] += 1
    with pytest.raises(ValidationError, match="index"):
        Result.model_validate(payload)
    payload["run"]["repetition"] = 0
    payload["config"].update(condition="cold", warmups=0)
    payload["run"]["condition"] = "cold"
    with pytest.raises(ValidationError, match="index"):
        Result.model_validate(payload)


@pytest.mark.parametrize(
    "mutation",
    [
        "complete-errors",
        "failed-no-errors",
        "failed-wrong-error",
        "cancelled-wrong-error",
        "failure-as-cancellation",
        "raw-message",
    ],
)
def test_result_errors_match_the_terminal_outcome(mutation: str) -> None:
    payload = load_fixture("result-failed")
    if mutation == "complete-errors":
        payload = load_fixture("result-complete")
        payload["errors"] = [{"code": "timeout", "stage": "generation"}]
    elif mutation == "failed-no-errors":
        payload["errors"] = []
    elif mutation == "failed-wrong-error":
        payload["errors"][0]["code"] = "out_of_memory"
    elif mutation == "cancelled-wrong-error":
        payload["run"]["state"] = "cancelled"
    elif mutation == "failure-as-cancellation":
        payload["run"]["error_code"] = "cancelled"
        payload["errors"][0]["code"] = "cancelled"
    else:
        payload["errors"][0]["message"] = "raw private exception"
    with pytest.raises(ValidationError):
        Result.model_validate(payload)


def test_zero_and_missing_tokens_are_distinct() -> None:
    payload = load_fixture("result-complete")
    payload["run"]["output_tokens"] = 0
    assert Result.model_validate(payload).run.output_tokens == 0
    payload["run"]["output_tokens"] = None
    with pytest.raises(ValidationError, match="token counts"):
        Result.model_validate(payload)
