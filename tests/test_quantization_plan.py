"""Validate inert YAML plans only. No benchmark, conversion or hardware execution."""

import hashlib
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from inferlab_api.contracts import ExperimentConfig

ROOT = Path(__file__).resolve().parents[1] / "experiments/plans/rtx4060"
QUANTS = {"Q4_K_M", "Q5_K_M", "Q8_0", "FP16"}
CONTEXTS = {1024, 2048, 4096, 8192}
LAYERS = {0, 8, 16, 24}


def documents() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    def read(name: str) -> dict[str, Any]:
        return cast(dict[str, Any], yaml.safe_load((ROOT / name).read_text("utf-8")))

    return read("matrix.yaml"), read("artifacts.yaml"), read("prompts.yaml")


def checksum(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def validate_plan(
    matrix: dict[str, Any],
    artifacts: dict[str, Any],
    prompts: dict[str, Any],
    *,
    ready: bool = False,
) -> list[ExperimentConfig]:
    """Test-only document checks/materialization, not a worker import or executor."""
    assert matrix["readiness"] in {"draft_unpinned", "ready"}
    assert matrix["hardware"]["nominal_memory_mib"] == 8192
    assert matrix["hardware"]["device_name"] == "NVIDIA GeForce RTX 4060"
    assert artifacts["conversion"]["method"] == "direct_from_same_fp16"
    assert artifacts["conversion"]["importance_matrix"] == "none"
    source = artifacts["source"]
    variants = artifacts["variants"]
    assert len(variants) == 4 and {item["quantization"] for item in variants} == QUANTS
    assert len({item["model_id"] for item in variants}) == 4
    for item in variants:
        assert set(item) == {
            "model_id",
            "source_id",
            "quantization",
            "sha256",
            "file_bytes",
            "parent_fp16_sha256",
        }
        assert item["source_id"] == source["id"], "different model source"
    engine = matrix["engine"]
    assert engine["id"] == "llama.cpp" and engine["seed_supported"] is True
    for key in ("parallel", "threads", "threads_batch", "batch_size", "ubatch_size"):
        assert type(engine[key]) is int and engine[key] > 0
    assert engine["parallel"] == 1
    for key in ("cache_type_k", "cache_type_v"):
        assert engine[key] == "f16"
    for key in ("fit", "flash_attention"):
        assert engine[key] == "off"
    for key in (
        "cache_prompt",
        "context_shift",
        "startup_warmup",
        "idle_sleep",
        "speculative_decoding",
    ):
        assert engine[key] is False
    assert engine["raw_prompt"] is True and engine["thinking"] == "disabled"
    assert (
        engine["kv_offload"] is True and engine["adapters"] == "none" and engine["offline"] is True
    )
    assert engine["load_mode"] == "mmap" and engine["lazy_mode"] == "off"
    assert engine["split_mode"] == "none" and engine["main_gpu"] == 0
    assert engine["op_offload"] is False and engine["ignore_eos"] is False
    assert engine["top_k"] == 0 and engine["min_p"] == 0.0
    assert engine["repeat_penalty"] == 1.0 and engine["repeat_last_n"] == 0
    assert engine["stop"] == []
    common = matrix["common"]
    assert common["condition"] == "warm" and common["concurrency"] == 1
    assert type(common["repetitions"]) is int and 1 <= common["repetitions"] <= 20
    assert type(common["warmups"]) is int and 1 <= common["warmups"] <= 5
    assert common["max_output_tokens"] == 128 and common["input_token_budget"] == 512
    assert common["sampling"] == {"temperature": 0.0, "top_p": 1.0, "seed": 42}
    cooldown = matrix["cooldown"]
    assert 0 < cooldown["minimum_seconds"] <= cooldown["maximum_seconds"] <= 3600
    assert 0 < cooldown["stable_seconds"] <= cooldown["minimum_seconds"]
    assert cooldown["maximum_above_idle_c"] > 0 and cooldown["on_unverifiable"] == "defer_cell"
    assert matrix["feasibility"]["automatic_fallback"] is False
    assert matrix["feasibility"]["fp16"] == "conditional"
    assert matrix["feasibility"]["minimum_free_gpu_mib"] >= 1024
    assert matrix["feasibility"]["minimum_free_host_mib"] >= 2048
    assert matrix["feasibility"]["check_each_cell"] is True
    assert matrix["feasibility"]["compare_only_matching_cells"] is True
    assert prompts["rendering"] == "exact_raw_utf8_no_template"
    prompt_ids = [item["id"] for item in prompts["prompts"]]
    assert len(prompt_ids) == len(set(prompt_ids)) == 3
    assert matrix["order_policy"]["prompt_order"] == prompt_ids
    assert set(matrix["order_policy"]["first_order"]) == QUANTS
    assert len(matrix["order_policy"]["first_order"]) == 4
    assert matrix["order_policy"]["kind"] == "rotate_quantization_by_cell"
    assert matrix["order_policy"]["cell_order"] == [
        "c1024",
        "c2048",
        "c4096",
        "c8192",
        "l0",
        "l8",
        "l16",
        "l24",
    ]
    for prompt in prompts["prompts"]:
        assert hashlib.sha256(prompt["text"].encode("utf-8")).hexdigest() == prompt["sha256"]
    golden = {item["id"] for item in prompts["prompts"] if item["purpose"] == "quality"}
    assert set(matrix["quality"]["golden_prompts"]) == golden
    assert all(item["expected"] is not None for item in prompts["prompts"] if item["id"] in golden)
    assert matrix["quality"]["required_pass_fraction"] == 1.0
    assert matrix["quality"]["reference_requires_matching_cell"] is True
    assert matrix["quality"]["output_length_policy"] == "stratify_actual_tokens"
    assert matrix["quality"]["preferred_reference"] == "FP16"
    assert matrix["quality"]["fallback_reference"] == "Q8_0"
    expected_answers = {item["id"]: item["expected"] for item in prompts["prompts"]}
    assert expected_answers["quality-arithmetic"] == {"kind": "exact_trimmed_text", "value": "42"}
    assert expected_answers["quality-extraction"] == {
        "kind": "exact_json_object",
        "value": {"name": "Mira", "color": "blue"},
    }
    trials = matrix["trials"]
    assert len(trials) == len({item["id"] for item in trials}) == 32
    combinations: set[tuple[str, str, int, int]] = set()
    for trial in trials:
        assert set(trial) == {
            "id",
            "series",
            "quantization",
            "context_tokens",
            "gpu_layers",
            "admission",
            "skip_reason",
        }
        assert trial["quantization"] in QUANTS
        assert type(trial["gpu_layers"]) is int and type(trial["context_tokens"]) is int
        if trial["series"] == "context":
            assert trial["gpu_layers"] == 8, "context sweep changes GPU layers"
            assert trial["context_tokens"] in CONTEXTS
        else:
            assert trial["series"] == "layers"
            assert trial["context_tokens"] == 2048, "layer sweep changes context"
            assert trial["gpu_layers"] in LAYERS
        combinations.add(
            (trial["series"], trial["quantization"], trial["context_tokens"], trial["gpu_layers"])
        )
        assert trial["admission"] in {"pending", "admitted", "skipped"}
        if trial["admission"] == "skipped":
            assert trial["skip_reason"] in {
                "vram_headroom",
                "host_memory",
                "oom",
                "artifact_unavailable",
                "unsupported",
                "thermal_timeout",
            }
        else:
            assert trial["skip_reason"] is None
        assert common["input_token_budget"] + common["max_output_tokens"] <= trial["context_tokens"]
    expected = {("context", quant, context, 8) for quant in QUANTS for context in CONTEXTS}
    expected |= {("layers", quant, 2048, layers) for quant in QUANTS for layers in LAYERS}
    assert combinations == expected, "missing or duplicated matrix cell"
    if not ready:
        return []
    assert matrix["readiness"] == "ready", "plan is not ready"
    assert isinstance(source["model_id"], str) and source["model_id"]
    assert isinstance(source["revision"], str) and re.fullmatch(
        r"[a-f0-9]{40}|[a-f0-9]{64}", source["revision"]
    )
    for key in ("snapshot_sha256", "tokenizer_sha256", "prompt_template_sha256"):
        assert checksum(source[key]), "unpinned source metadata"
    assert source["transformer_layers"] >= max(LAYERS)
    assert source["max_context_tokens"] >= max(CONTEXTS)
    assert all(artifacts["conversion"][key] for key in ("converter_build", "quantizer_build"))
    assert all(
        matrix["hardware"][key] is not None
        for key in ("form_factor", "driver_version", "cpu_model", "host_memory_mib", "power_mode")
    )
    assert engine["version"] and engine["build"] and checksum(engine["binary_sha256"])
    assert len({item["sha256"] for item in variants}) == 4, "quantized files need distinct hashes"
    fp16 = next(item for item in variants if item["quantization"] == "FP16")
    for variant in variants:
        assert checksum(variant["sha256"])
        assert type(variant["file_bytes"]) is int and variant["file_bytes"] > 0
        assert variant["parent_fp16_sha256"] == (None if variant is fp16 else fp16["sha256"])
    configs: list[ExperimentConfig] = []
    for trial in trials:
        assert trial["admission"] != "pending", "cell feasibility is unresolved"
        if trial["admission"] == "skipped":
            continue
        variant = next(item for item in variants if item["quantization"] == trial["quantization"])
        for prompt in prompts["prompts"]:
            assert (
                type(prompt["input_tokens"]) is int
                and 0 < prompt["input_tokens"] <= common["input_token_budget"]
            )
            configs.append(
                ExperimentConfig.model_validate(
                    {
                        **common,
                        "experiment_id": f"RTX4060-{trial['id']}-{prompt['id']}",
                        "engine_id": engine["id"],
                        "engine_version": engine["version"],
                        "engine_build": engine["build"],
                        "seed_supported": engine["seed_supported"],
                        "model_id": variant["model_id"],
                        "model_revision": source["revision"],
                        "model_sha256": variant["sha256"],
                        "quantization": variant["quantization"],
                        "workload_id": f"{prompts['suite_id']}.{prompt['id']}",
                        "prompt_id": prompt["id"],
                        "gpu_device_id": matrix["hardware"]["gpu_device_id"],
                        "context_tokens": trial["context_tokens"],
                        "gpu_layers": trial["gpu_layers"],
                    }
                )
            )
    assert len({config.experiment_id for config in configs}) == len(configs)
    return configs


def synthetic_ready() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Test doubles only; these values are never written into the real YAML plan."""
    matrix, artifacts, prompts = documents()
    matrix["readiness"] = "ready"
    matrix["hardware"].update(
        form_factor="laptop",
        driver_version="TEST-DRIVER",
        cpu_model="TEST-CPU",
        host_memory_mib=32768,
        power_mode="TEST-AC",
    )
    matrix["engine"].update(version="TEST-VERSION", build="TEST-BUILD", binary_sha256="d" * 64)
    artifacts["source"].update(
        model_id="SYNTHETIC-TEST-MODEL",
        revision="c" * 40,
        snapshot_sha256="a" * 64,
        tokenizer_sha256="b" * 64,
        prompt_template_sha256="e" * 64,
        transformer_layers=32,
        max_context_tokens=8192,
    )
    artifacts["conversion"].update(
        converter_build="TEST-CONVERTER", quantizer_build="TEST-QUANTIZER"
    )
    for variant in artifacts["variants"]:
        variant.update(
            sha256=hashlib.sha256(f"SYNTHETIC-{variant['quantization']}".encode()).hexdigest(),
            file_bytes=12345,
        )
    fp16 = next(item for item in artifacts["variants"] if item["quantization"] == "FP16")
    for variant in artifacts["variants"]:
        if variant is not fp16:
            variant["parent_fp16_sha256"] = fp16["sha256"]
    for trial in matrix["trials"]:
        trial["admission"] = "admitted"
    for prompt in prompts["prompts"]:
        prompt["input_tokens"] = 128  # Synthetic tokenization evidence, not a measured count.
    return matrix, artifacts, prompts


def test_draft_has_controlled_complete_matrix_and_cannot_be_ready() -> None:
    matrix, artifacts, prompts = documents()
    validate_plan(matrix, artifacts, prompts)
    with pytest.raises(AssertionError, match="not ready"):
        validate_plan(matrix, artifacts, prompts, ready=True)


def test_synthetic_pinned_plan_maps_to_existing_configs_with_stable_ids() -> None:
    configs = validate_plan(*synthetic_ready(), ready=True)
    assert len(configs) == 96
    assert len({config.model_revision for config in configs}) == 1
    assert {config.quantization for config in configs} == QUANTS
    assert all(config.repetitions == 8 and config.warmups == 2 for config in configs)


@pytest.mark.parametrize(
    "mutation",
    [
        "context-confound",
        "layer-confound",
        "duplicate-cell",
        "missing-quant",
        "other-source",
        "per-variant-revision",
        "prompt-drift",
        "seed-drift",
        "auto-fit",
        "kv-quantization",
        "automatic-fallback",
        "no-cooldown",
        "unmatched-quality-reference",
        "unknown-field",
    ],
)
def test_invalid_plan_controls_rejected(mutation: str) -> None:
    matrix, artifacts, prompts = documents()
    if mutation == "context-confound":
        matrix["trials"][0]["gpu_layers"] = 16
    elif mutation == "layer-confound":
        matrix["trials"][-1]["context_tokens"] = 4096
    elif mutation == "duplicate-cell":
        matrix["trials"][1] = deepcopy(matrix["trials"][0])
    elif mutation == "missing-quant":
        artifacts["variants"].pop()
    elif mutation == "other-source":
        artifacts["variants"][0]["source_id"] = "other-source"
    elif mutation == "per-variant-revision":
        artifacts["variants"][0]["revision"] = "different"
    elif mutation == "prompt-drift":
        prompts["prompts"][0]["text"] += " "
    elif mutation == "seed-drift":
        matrix["common"]["sampling"]["seed"] = 43
    elif mutation == "auto-fit":
        matrix["engine"]["fit"] = "on"
    elif mutation == "kv-quantization":
        matrix["engine"]["cache_type_k"] = "q8_0"
    elif mutation == "automatic-fallback":
        matrix["feasibility"]["automatic_fallback"] = True
    elif mutation == "no-cooldown":
        matrix["cooldown"]["minimum_seconds"] = 0
    elif mutation == "unmatched-quality-reference":
        matrix["quality"]["reference_requires_matching_cell"] = False
    else:
        matrix["trials"][0]["shell_command"] = "never execute"
    with pytest.raises(AssertionError):
        validate_plan(matrix, artifacts, prompts)


@pytest.mark.parametrize(
    "mutation", ["revision", "same-hash", "parent", "layers", "pending", "tokens"]
)
def test_pinning_and_feasibility_are_required_for_ready_plan(mutation: str) -> None:
    matrix, artifacts, prompts = synthetic_ready()
    if mutation == "revision":
        artifacts["source"]["revision"] = "main"
    elif mutation == "same-hash":
        artifacts["variants"][0]["sha256"] = artifacts["variants"][1]["sha256"]
    elif mutation == "parent":
        artifacts["variants"][0]["parent_fp16_sha256"] = "f" * 64
    elif mutation == "layers":
        artifacts["source"]["transformer_layers"] = 16
    elif mutation == "pending":
        matrix["trials"][0]["admission"] = "pending"
    else:
        prompts["prompts"][0]["input_tokens"] = None
    with pytest.raises(AssertionError):
        validate_plan(matrix, artifacts, prompts, ready=True)


def test_infeasible_fp16_cells_remain_visible_without_changed_settings() -> None:
    matrix, artifacts, prompts = synthetic_ready()
    for trial in matrix["trials"]:
        if trial["quantization"] == "FP16":
            trial.update(admission="skipped", skip_reason="vram_headroom")
    configs = validate_plan(matrix, artifacts, prompts, ready=True)
    assert len(configs) == 72 and len(matrix["trials"]) == 32
    assert all(config.quantization != "FP16" for config in configs)
