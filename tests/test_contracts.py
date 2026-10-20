"""Contract boundaries and provenance checks, never benchmark calculations."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError

from inferlab_api.contracts import (
    ContractCatalog,
    ExperimentConfig,
    ExperimentSubmitRequest,
    Job,
    Milliseconds,
    PublishedReport,
    Registry,
    RunMetrics,
    Summary,
    WorkerHeartbeat,
    validate_submission,
)

FIXTURES = Path(__file__).resolve().parents[1] / "contracts/fixtures/demo.json"


@pytest.fixture
def payload() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(FIXTURES.read_text(encoding="utf-8")))


def test_all_wire_fixtures_validate_and_keep_availability_separate(payload: dict[str, Any]) -> None:
    catalog = ContractCatalog.model_validate(payload)
    assert set(catalog.display_states) == {
        "unavailable",
        "pending",
        "running",
        "complete",
        "failed",
        "cancelled",
    }
    assert {job.phase for job in catalog.job_scenarios} == {
        "queued",
        "leased",
        "running",
        "completed",
        "failed",
        "cancelled",
    }
    assert catalog.unavailable_response.data is None
    assert catalog.worker.state == "complete" and catalog.worker.data.availability == "offline"
    assert catalog.reports.state == "complete" and catalog.reports.data
    assert all(report.label == "DEMO DATA" for report in catalog.reports.data)


@pytest.mark.parametrize(
    "field,value",
    [
        ("context_tokens", 8193),
        ("context_tokens", 127),
        ("max_output_tokens", 2049),
        ("max_output_tokens", 0),
        ("repetitions", 21),
        ("warmups", 6),
        ("concurrency", 2),
        ("timeout_seconds", 3601),
        ("timeout_seconds", 0),
        ("repetitions", True),
        ("repetitions", "2"),
        ("model_id", "../../private"),
        ("model_id", "https://untrusted.example/model"),
        ("command", "run-this"),
    ],
)
def test_unsafe_or_unbounded_configs_rejected(
    payload: dict[str, Any], field: str, value: object
) -> None:
    config = deepcopy(payload["submit_request"]["config"])
    config[field] = value
    with pytest.raises(ValidationError):
        ExperimentConfig.model_validate(config)


def test_context_budget_and_cold_warmup_rules(payload: dict[str, Any]) -> None:
    config = deepcopy(payload["submit_request"]["config"])
    config.update(context_tokens=128, input_token_budget=100, max_output_tokens=100)
    with pytest.raises(ValidationError, match="budgets"):
        ExperimentConfig.model_validate(config)
    config = deepcopy(payload["submit_request"]["config"])
    config["condition"] = "cold"
    with pytest.raises(ValidationError, match="warmups"):
        ExperimentConfig.model_validate(config)


def test_registry_resolution_and_seed_capability(payload: dict[str, Any]) -> None:
    request = ExperimentSubmitRequest.model_validate(payload["submit_request"])
    registry = Registry.model_validate(payload["registry"]["data"])
    validate_submission(request, registry)
    unknown = request.model_dump()
    unknown["config"]["model_id"] = "not-registered"
    with pytest.raises(ValueError, match="Unknown"):
        validate_submission(ExperimentSubmitRequest.model_validate(unknown), registry)
    registry_data = registry.model_dump()
    registry_data["engines"][0]["seed_supported"] = False
    with pytest.raises(ValueError, match="seed"):
        validate_submission(request, Registry.model_validate(registry_data))


@pytest.mark.parametrize(
    "metric",
    [
        {"value": None, "unit": "ms", "unavailable_reason": None},
        {"value": 0.0, "unit": "ms", "unavailable_reason": "not_measured"},
        {"value": -1.0, "unit": "ms", "unavailable_reason": None},
        {"value": float("nan"), "unit": "ms", "unavailable_reason": None},
        {"value": float("inf"), "unit": "ms", "unavailable_reason": None},
        {"value": True, "unit": "ms", "unavailable_reason": None},
        {"value": 1.0, "unit": "ns", "unavailable_reason": None},
    ],
)
def test_invalid_metrics_never_become_zero(metric: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Milliseconds.model_validate(metric)


def test_missing_metric_and_genuine_zero_are_distinct() -> None:
    missing = Milliseconds(value=None, unit="ms", unavailable_reason="unsupported")
    zero = Milliseconds(value=0.0, unit="ms", unavailable_reason=None)
    assert missing.model_dump()["value"] is None
    assert zero.model_dump()["value"] == 0.0


def test_job_cannot_complete_or_fail_by_availability_alone(payload: dict[str, Any]) -> None:
    job = deepcopy(payload["job_scenarios"][0])
    job["state"] = "complete"
    with pytest.raises(ValidationError, match="phase"):
        Job.model_validate(job)
    job = deepcopy(payload["job_scenarios"][3])
    job["finished_at"] = None
    with pytest.raises(ValidationError, match="finish"):
        Job.model_validate(job)
    job = deepcopy(payload["job_scenarios"][3])
    job["cancellation_requested"] = True
    with pytest.raises(ValidationError, match="cancellation"):
        Job.model_validate(job)


@pytest.mark.parametrize(
    "mutation",
    [
        "warmup",
        "failed",
        "cold",
        "run-id",
        "label",
        "private-field",
        "mixed-attempts",
        "duplicate-repetition",
        "output-budget",
    ],
)
def test_reports_reject_invalid_evidence(payload: dict[str, Any], mutation: str) -> None:
    report = deepcopy(payload["reports"]["data"][0])
    if mutation == "warmup":
        report["runs"][0]["kind"] = "warmup"
    elif mutation == "failed":
        report["runs"][0].update(state="failed", error_code="timeout")
    elif mutation == "cold":
        report["runs"][0]["condition"] = "cold"
    elif mutation == "run-id":
        report["runs"][0]["id"] = "unrelated-run"
    elif mutation == "label":
        report["label"] = "MEASURED DATA"
    elif mutation in ("mixed-attempts", "duplicate-repetition"):
        second = deepcopy(report["runs"][0])
        second["id"] = "RUN-extra"
        if mutation == "mixed-attempts":
            second.update(attempt=2, repetition=1)
        report["runs"].append(second)
        report["summary"]["accepted_run_ids"].append(second["id"])
        report["summary"]["sample_count"] = 2
        report["config"]["repetitions"] = 2
    elif mutation == "output-budget":
        report["runs"][0]["output_tokens"] = 2049
    else:
        report["local_path"] = "private-file"
    with pytest.raises(ValidationError):
        PublishedReport.model_validate(report)


def test_summary_counts_are_traceable_and_incomplete_runs_stay_incomplete(
    payload: dict[str, Any],
) -> None:
    summary = deepcopy(payload["summaries"]["data"][0])
    summary["sample_count"] = 2
    with pytest.raises(ValidationError, match="count"):
        Summary.model_validate(summary)
    run = deepcopy(payload["runs"]["data"][0])
    run["input_tokens"] = None
    with pytest.raises(ValidationError, match="token counts"):
        RunMetrics.model_validate(run)


def test_heartbeat_threshold_unknown_and_timezone(payload: dict[str, Any]) -> None:
    heartbeat = deepcopy(payload["worker"]["data"])
    heartbeat.update(availability="online", mode="idle", observed_at="2026-10-18T09:02:30Z")
    assert WorkerHeartbeat.model_validate(heartbeat).availability == "online"  # exactly 90s
    heartbeat["observed_at"] = "2026-10-18T09:02:31Z"
    with pytest.raises(ValidationError, match="threshold"):
        WorkerHeartbeat.model_validate(heartbeat)
    heartbeat.update(availability="unknown", mode=None, last_seen_at=None)
    WorkerHeartbeat.model_validate(heartbeat)
    heartbeat["mode"] = "running"
    with pytest.raises(ValidationError, match="live execution"):
        WorkerHeartbeat.model_validate(heartbeat)
    heartbeat.update(mode=None, observed_at="2026-10-18T09:02:31")
    with pytest.raises(ValidationError):
        WorkerHeartbeat.model_validate(heartbeat)
