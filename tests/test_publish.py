"""Static publication boundary: validation, checksums, privacy and atomic replacement."""

import copy
import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from inferlab_api.contracts import PublishedReport
from inferlab_api.database.models import report_payload_sha256
from inferlab_api.publish import (
    Manifest,
    MethodologySnapshot,
    ModelsSnapshot,
    PublicationError,
    load_reports_from_database,
    main,
    publish_reports,
)

ROOT = Path(__file__).resolve().parents[1]
DEMO: dict[str, Any] = json.loads((ROOT / "contracts/fixtures/demo.json").read_text("utf-8"))
PUBLISHED_AT = datetime(2026, 10, 29, 12, tzinfo=UTC)


def demo_reports() -> list[PublishedReport]:
    return [PublishedReport.model_validate(item) for item in DEMO["reports"]["data"]]


def publish(
    output: Path, reports: list[PublishedReport], release_id: str = "REL-test-001"
) -> Manifest:
    return publish_reports(
        reports,
        output,
        release_id=release_id,
        published_at=PUBLISHED_AT,
    )


def test_release_writes_manifest_checksums_and_only_published_reports(tmp_path: Path) -> None:
    reports = demo_reports()
    manifest = publish(tmp_path, reports)
    root = tmp_path / "v1"
    raw = json.loads((root / "manifest.json").read_text("utf-8"))
    assert Manifest.model_validate(raw) == manifest
    assert manifest.report_count == 3
    assert manifest.label == "DEMO DATA"
    assert manifest.data_kind == "demo"
    assert {entry.id for entry in manifest.reports} == {report.id for report in reports}
    for entry in manifest.reports:
        data = (root / entry.path.removeprefix("/data/v1/")).read_bytes()
        assert len(data) == entry.size
        assert hashlib.sha256(data).hexdigest() == entry.sha256
        report = PublishedReport.model_validate_json(data)
        assert report.id == entry.id
        assert report.summary.sample_count == entry.sample_count
    models = ModelsSnapshot.model_validate_json(
        (root / manifest.models.path.removeprefix("/data/v1/")).read_bytes()
    )
    assert {model.id for model in models.models} == {"llama", "qwen", "gemma"}
    methodology = MethodologySnapshot.model_validate_json(
        (root / manifest.methodology.path.removeprefix("/data/v1/")).read_bytes()
    )
    assert methodology.methodology_versions == ["demo-v1"]
    public_text = (root / "manifest.json").read_text("utf-8") + "".join(
        (root / entry.path.removeprefix("/data/v1/")).read_text("utf-8")
        for entry in manifest.reports
    )
    assert "EXP-002" not in public_text
    assert "C:\\" not in public_text
    assert "password=" not in public_text


@pytest.mark.parametrize(
    "description",
    [
        "password=hunter2",
        "C:\\Users\\owner\\private-prompt.txt",
        "-----BEGIN " + "PRIVATE KEY-----",
        "Traceback (most recent call last):",
    ],
)
def test_privacy_canaries_abort_before_replacing_previous_release(
    tmp_path: Path, description: str
) -> None:
    reports = demo_reports()
    publish(tmp_path, reports)
    manifest_path = tmp_path / "v1" / "manifest.json"
    before = manifest_path.read_bytes()
    bad = copy.deepcopy(reports)
    bad[0] = bad[0].model_copy(update={"description": description})
    with pytest.raises(PublicationError, match="canary"):
        publish(tmp_path, bad, "REL-bad-001")
    assert manifest_path.read_bytes() == before
    assert (tmp_path / "v1" / "manifest.json").read_text("utf-8") == before.decode("utf-8")


def test_missing_provenance_and_invalid_reports_are_rejected(tmp_path: Path) -> None:
    bad = demo_reports()
    bad[0] = bad[0].model_copy(update={"provenance": None})
    with pytest.raises(ValidationError):
        publish(tmp_path, bad)
    assert not (tmp_path / "v1").exists()


def test_empty_release_is_a_valid_honest_empty_snapshot(tmp_path: Path) -> None:
    manifest = publish(tmp_path, [])
    assert manifest.report_count == 0
    assert manifest.reports == []
    assert manifest.label == "DEMO DATA"
    models = ModelsSnapshot.model_validate_json(
        (tmp_path / "v1" / manifest.models.path.removeprefix("/data/v1/")).read_bytes()
    )
    assert models.models == []


def test_mixed_release_label_is_disclosed(tmp_path: Path) -> None:
    reports = demo_reports()
    reports[0] = reports[0].model_copy(update={"data_kind": "measured", "label": "MEASURED DATA"})
    manifest = publish(tmp_path, reports)
    assert manifest.label == "MIXED DATA"
    assert manifest.data_kind == "mixed"
    assert {entry.label for entry in manifest.reports} == {"DEMO DATA", "MEASURED DATA"}


def test_database_loader_checks_stored_checksums(tmp_path: Path) -> None:
    database = tmp_path / "api.db"
    reports = demo_reports()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE published_reports ("
            "id VARCHAR(64) PRIMARY KEY, experiment_id VARCHAR(64) NOT NULL, "
            "payload_sha256 VARCHAR(64) NOT NULL, payload JSON NOT NULL, "
            "published_at DATETIME NOT NULL)"
        )
        for report in reports:
            payload = report.model_dump(mode="json")
            connection.execute(
                "INSERT INTO published_reports VALUES (?, ?, ?, ?, ?)",
                (
                    report.id,
                    report.config.experiment_id,
                    report_payload_sha256(payload),
                    json.dumps(payload),
                    report.published_at.replace(tzinfo=None).isoformat(sep=" "),
                ),
            )
    loaded = load_reports_from_database("sqlite:///" + database.as_posix())
    assert {report.id for report in loaded} == {report.id for report in reports}

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE published_reports SET payload_sha256 = ? WHERE id = ?",
            ("f" * 64, reports[0].id),
        )
    with pytest.raises(PublicationError, match="checksum"):
        load_reports_from_database("sqlite:///" + database.as_posix())


def test_cli_validates_fixture_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "data"
    code = main(
        [
            "--fixture",
            str(ROOT / "contracts/fixtures/demo.json"),
            "--output",
            str(output),
            "--release-id",
            "REL-cli-001",
            "--published-at",
            "2026-10-29T12:00:00Z",
            "--validate-only",
        ]
    )
    assert code == 0
    assert '"written": false' in capsys.readouterr().out
    assert not output.exists()


def test_release_identifier_cannot_escape_the_output_directory(tmp_path: Path) -> None:
    output = tmp_path / "data"
    with pytest.raises(ValidationError):
        publish(output, demo_reports(), "../../escape")
    assert not output.exists()
    assert not (tmp_path / "escape").exists()


def test_manifest_binds_paths_to_identifiers_and_checksums(tmp_path: Path) -> None:
    manifest = publish(tmp_path, demo_reports())
    data = manifest.model_dump(mode="json")

    traversal_path = copy.deepcopy(data)
    traversal_path["reports"][0]["path"] = (
        "/data/v1/reports/../../private." + traversal_path["reports"][0]["sha256"] + ".json"
    )
    with pytest.raises(ValidationError):
        Manifest.model_validate(traversal_path)

    checksum_path = copy.deepcopy(data)
    checksum_path["reports"][0]["sha256"] = "f" * 64
    with pytest.raises(ValidationError, match="bind"):
        Manifest.model_validate(checksum_path)

    duplicate = copy.deepcopy(data)
    duplicate["reports"].append(copy.deepcopy(duplicate["reports"][0]))
    duplicate["report_count"] = len(duplicate["reports"])
    with pytest.raises(ValidationError, match="unique"):
        Manifest.model_validate(duplicate)

    bad_asset = copy.deepcopy(data)
    bad_asset["models"]["path"] = "/data/v1/models/../../private.json"
    with pytest.raises(ValidationError):
        Manifest.model_validate(bad_asset)

    oversized = copy.deepcopy(data)
    oversized["models"]["size"] = 5_242_881
    with pytest.raises(ValidationError):
        Manifest.model_validate(oversized)


def test_snapshot_contracts_reject_duplicate_models_and_methodology_versions() -> None:
    reports = demo_reports()
    models = [report.provenance.model for report in reports]
    with pytest.raises(ValidationError, match="unique"):
        ModelsSnapshot.model_validate(
            {"schema_version": "1.0", "label": "DEMO DATA", "models": models + models[:1]}
        )
    with pytest.raises(ValidationError, match="unique"):
        MethodologySnapshot.model_validate(
            {
                "schema_version": "1.0",
                "methodology_versions": ["demo-v1", "demo-v1"],
                "metrics": [
                    {
                        "key": "ttft",
                        "label": "Time to first token",
                        "unit": "ms",
                        "direction": "lower",
                        "description": "Client-observed time to first content.",
                    }
                ],
                "conditions": ["warm"],
                "protocol": ["Keep conditions separate."],
                "limitations": ["Missing values remain unavailable."],
            }
        )
