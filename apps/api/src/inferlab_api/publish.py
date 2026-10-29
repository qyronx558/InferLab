"""Explicit, validated export of reviewed reports into static public snapshots."""

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import sqlalchemy as sa
from pydantic import AwareDatetime, Field, ValidationError, model_validator
from sqlalchemy.orm import Session

from inferlab_api.contracts import (
    Checksum,
    Contract,
    Engine,
    Identifier,
    Model,
    PublishedReport,
    ShortText,
    Workload,
)
from inferlab_api.database.models import PublishedReport as PublishedReportRow
from inferlab_api.database.models import report_payload_sha256
from inferlab_api.database.session import create_database_engine

SNAPSHOT_SCHEMA_VERSION = "1.0"
MAX_REPORTS: Literal[100] = 100
MAX_FILES: Literal[2000] = 2_000
MAX_ASSET_BYTES: Literal[5_242_880] = 5_242_880
REPORT_PATH = r"^/data/v1/reports/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.[a-f0-9]{64}\.json$"
MODELS_PATH = r"^/data/v1/models\.[a-f0-9]{64}\.json$"
METHODOLOGY_PATH = r"^/data/v1/methodology\.[a-f0-9]{64}\.json$"
ASSET_PATH = rf"^(?:{REPORT_PATH[1:-1]}|{MODELS_PATH[1:-1]}|{METHODOLOGY_PATH[1:-1]})$"

FORBIDDEN_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "authorization",
        "command",
        "cookie",
        "cookies",
        "csrf",
        "csrf_token",
        "cwd",
        "email",
        "env",
        "environment",
        "file_path",
        "hostname",
        "ip_address",
        "local_path",
        "log",
        "logs",
        "messages",
        "password",
        "passwd",
        "path",
        "private_key",
        "prompt",
        "prompt_text",
        "raw_log",
        "raw_logs",
        "refresh_token",
        "secret",
        "session",
        "session_id",
        "system_prompt",
        "trace",
        "traceback",
        "user_prompt",
        "username",
    }
)
FORBIDDEN_VALUE_PATTERNS = (
    re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|refresh[_-]?token"
        r"|authorization|bearer|private[_-]?key)\b\s*[:=]\s*\S+"
    ),
    re.compile(r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"(?i)\b[A-Za-z]:[\\/]"),
    re.compile(r"\\\\[A-Za-z0-9._-]+\\"),
    re.compile(r"(?:^|[\s\"'(=])(?:/(?:home|Users|tmp|var|private|root|etc|opt|mnt|Volumes)/)"),
    re.compile(r"(?i)\bfile://"),
    re.compile(r"(?:^|[\s\"'(=])~[/\\]"),
    re.compile(r"(?i)Traceback \(most recent call last\)"),
    re.compile(r"(?i)\bFile \"[^\"]+\", line \d+"),
)


class PublicationError(ValueError):
    """A release failed validation before any public artifact was replaced."""


class ReleaseLimits(Contract):
    max_reports: Literal[100]
    max_files: Literal[2000]
    max_asset_bytes: Literal[5_242_880]


class AssetReference(Contract):
    path: Annotated[str, Field(pattern=ASSET_PATH)]
    sha256: Checksum
    size: Annotated[int, Field(strict=True, ge=1, le=MAX_ASSET_BYTES)]


class ManifestReport(Contract):
    id: Identifier
    title: ShortText
    description: Annotated[str, Field(min_length=1, max_length=500)]
    category: ShortText
    data_kind: Literal["demo", "measured"]
    label: Literal["DEMO DATA", "MEASURED DATA"]
    published_at: AwareDatetime
    experiment_id: Identifier
    engine_id: Literal["ollama", "llama.cpp"]
    model_id: Identifier
    methodology_version: Identifier
    condition: Literal["warm", "cold"]
    sample_count: Annotated[int, Field(strict=True, ge=0, le=20)]
    path: Annotated[str, Field(pattern=REPORT_PATH)]
    sha256: Checksum
    size: Annotated[int, Field(strict=True, ge=1, le=MAX_ASSET_BYTES)]


class Manifest(Contract):
    schema_version: Literal["1.0"]
    release_id: Identifier
    published_at: AwareDatetime
    label: Literal["DEMO DATA", "MEASURED DATA", "MIXED DATA"]
    data_kind: Literal["demo", "measured", "mixed"]
    report_count: Annotated[int, Field(strict=True, ge=0, le=MAX_REPORTS)]
    reports: Annotated[list[ManifestReport], Field(max_length=MAX_REPORTS)]
    models: AssetReference
    methodology: AssetReference
    limits: ReleaseLimits

    @model_validator(mode="after")
    def consistent_manifest(self) -> Self:
        if self.report_count != len(self.reports):
            raise ValueError("Manifest report count must match its entries")
        ids = [report.id for report in self.reports]
        if len(set(ids)) != len(ids):
            raise ValueError("Manifest report identifiers must be unique")
        paths = [report.path for report in self.reports]
        if len(set(paths)) != len(paths):
            raise ValueError("Manifest report paths must be unique")
        for report in self.reports:
            expected = f"/data/v1/reports/{report.id}.{report.sha256}.json"
            if report.path != expected:
                raise ValueError("Manifest report path must bind its identifier and checksum")
        if self.models.path in paths or self.methodology.path in paths:
            raise ValueError("Manifest asset paths must be unique")
        if self.models.path == self.methodology.path:
            raise ValueError("Manifest asset paths must be unique")
        return self


class ModelsSnapshot(Contract):
    schema_version: Literal["1.0"]
    label: Literal["DEMO DATA", "MEASURED DATA", "MIXED DATA"]
    models: Annotated[list[Model], Field(max_length=100)]

    @model_validator(mode="after")
    def unique_models(self) -> Self:
        ids = [model.id for model in self.models]
        if len(set(ids)) != len(ids):
            raise ValueError("Snapshot model identifiers must be unique")
        return self


class MethodologyMetric(Contract):
    key: Identifier
    label: ShortText
    unit: ShortText
    direction: Literal["lower", "higher", "descriptive"]
    description: Annotated[str, Field(min_length=1, max_length=500)]


class MethodologySnapshot(Contract):
    schema_version: Literal["1.0"]
    methodology_versions: Annotated[list[Identifier], Field(max_length=20)]
    metrics: Annotated[list[MethodologyMetric], Field(min_length=1, max_length=20)]
    conditions: Annotated[list[Literal["warm", "cold"]], Field(min_length=1, max_length=2)]
    protocol: Annotated[list[ShortText], Field(min_length=1, max_length=20)]
    limitations: Annotated[list[ShortText], Field(min_length=1, max_length=20)]

    @model_validator(mode="after")
    def unique_versions(self) -> Self:
        if len(set(self.methodology_versions)) != len(self.methodology_versions):
            raise ValueError("Methodology versions must be unique")
        return self


METHODOLOGY = MethodologySnapshot(
    schema_version="1.0",
    methodology_versions=[],
    metrics=[
        MethodologyMetric(
            key="ttft",
            label="Time to first token",
            unit="ms",
            direction="lower",
            description="Client-observed time from request start to the first streamed token.",
        ),
        MethodologyMetric(
            key="request_latency",
            label="Request latency",
            unit="ms",
            direction="lower",
            description="Client-observed time to complete the entire streamed request.",
        ),
        MethodologyMetric(
            key="decode_throughput",
            label="Decode throughput",
            unit="tok/s",
            direction="higher",
            description="Accepted output tokens per second during generation.",
        ),
        MethodologyMetric(
            key="peak_vram",
            label="Peak VRAM",
            unit="MiB",
            direction="lower",
            description="Peak device memory observed under the documented sampling method.",
        ),
        MethodologyMetric(
            key="quality",
            label="Quality score",
            unit="score",
            direction="higher",
            description="Optional bounded quality score; unavailable when not measured.",
        ),
    ],
    conditions=["warm", "cold"],
    protocol=[
        "Pin the model revision, checksum, quantization, engine build, workload and "
        "device settings.",
        "Keep warm and cold conditions separate; do not merge their samples.",
        "Record every accepted measured run with units, token counts, timestamps and errors.",
        "Treat aggregate throughput as derived from accepted output tokens and summed latency.",
    ],
    limitations=[
        "Missing measurements remain unavailable and are never replaced with zero.",
        "Small samples and different hardware or workloads do not support general rankings.",
        "Comparisons are observational unless every relevant condition was controlled.",
    ],
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def _assert_public(value: object, location: str = "artifact") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise PublicationError(f"{location} contains a non-string key")
            if key.lower() in FORBIDDEN_KEYS:
                raise PublicationError(f"{location} contains forbidden field {key!r}")
            _assert_public(item, f"{location}.{key}")
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_public(item, f"{location}[{index}]")
        return
    if isinstance(value, str):
        for pattern in FORBIDDEN_VALUE_PATTERNS:
            if pattern.search(value):
                raise PublicationError(f"{location} contains a secret, path or raw-log canary")


def _normalized_reports(reports: Sequence[PublishedReport]) -> list[PublishedReport]:
    if len(reports) > MAX_REPORTS:
        raise PublicationError(f"A release may contain at most {MAX_REPORTS} reports")
    normalized = [PublishedReport.model_validate(report.model_dump()) for report in reports]
    ids = [report.id for report in normalized]
    if len(set(ids)) != len(ids):
        raise PublicationError("Report identifiers must be unique")
    hashes = [report_payload_sha256(report.model_dump(mode="json")) for report in normalized]
    if len(set(hashes)) != len(hashes):
        raise PublicationError("Report payloads must be unique")
    return sorted(
        normalized,
        key=lambda report: (report.published_at, report.id),
        reverse=True,
    )


def _release_label(
    reports: Sequence[PublishedReport],
) -> tuple[
    Literal["DEMO DATA", "MEASURED DATA", "MIXED DATA"],
    Literal["demo", "measured", "mixed"],
]:
    kinds = {report.data_kind for report in reports}
    if kinds == {"measured"}:
        return "MEASURED DATA", "measured"
    if kinds == {"demo", "measured"}:
        return "MIXED DATA", "mixed"
    return "DEMO DATA", "demo"


def _public_metadata(
    reports: Sequence[PublishedReport],
) -> tuple[list[Model], list[Engine], list[Workload]]:
    models: dict[str, Model] = {}
    engines: dict[str, Engine] = {}
    workloads: dict[str, Workload] = {}
    for report in reports:
        model = report.provenance.model
        engine = report.provenance.engine
        workload = report.provenance.workload
        if model.id in models and models[model.id] != model:
            raise PublicationError(f"Model {model.id!r} has conflicting public metadata")
        if engine.id in engines and engines[engine.id] != engine:
            raise PublicationError(f"Engine {engine.id!r} has conflicting public metadata")
        if workload.id in workloads and workloads[workload.id] != workload:
            raise PublicationError(f"Workload {workload.id!r} has conflicting public metadata")
        models[model.id] = model
        engines[engine.id] = engine
        workloads[workload.id] = workload
    return (
        [models[key] for key in sorted(models)],
        [engines[key] for key in sorted(engines)],
        [workloads[key] for key in sorted(workloads)],
    )


def _build_release(
    reports: Sequence[PublishedReport],
    release_id: str,
    published_at: datetime,
) -> tuple[Manifest, dict[str, bytes]]:
    normalized = _normalized_reports(reports)
    label, data_kind = _release_label(normalized)
    models, _, _ = _public_metadata(normalized)
    methodology_versions = sorted({report.provenance.methodology_version for report in normalized})
    methodology = MethodologySnapshot(
        schema_version=METHODOLOGY.schema_version,
        methodology_versions=methodology_versions,
        metrics=METHODOLOGY.metrics,
        conditions=METHODOLOGY.conditions,
        protocol=METHODOLOGY.protocol,
        limitations=METHODOLOGY.limitations,
    )
    assets: dict[str, bytes] = {}
    manifest_reports: list[ManifestReport] = []
    for report in normalized:
        payload = report.model_dump(mode="json")
        _assert_public(payload, f"report {report.id}")
        data = _json_bytes(payload)
        digest = _sha256(data)
        path = f"/data/v1/reports/{report.id}.{digest}.json"
        assets[path] = data
        manifest_reports.append(
            ManifestReport(
                id=report.id,
                title=report.title,
                description=report.description,
                category=report.category,
                data_kind=report.data_kind,
                label=report.label,
                published_at=report.published_at,
                experiment_id=report.config.experiment_id,
                engine_id=report.config.engine_id,
                model_id=report.config.model_id,
                methodology_version=report.provenance.methodology_version,
                condition=report.config.condition,
                sample_count=report.summary.sample_count,
                path=path,
                sha256=digest,
                size=len(data),
            )
        )

    models_snapshot = ModelsSnapshot(schema_version="1.0", label=label, models=models)
    models_data = _json_bytes(models_snapshot.model_dump(mode="json"))
    _assert_public(models_snapshot.model_dump(mode="json"), "models")
    models_digest = _sha256(models_data)
    models_path = f"/data/v1/models.{models_digest}.json"
    assets[models_path] = models_data

    methodology_data = _json_bytes(methodology.model_dump(mode="json"))
    _assert_public(methodology.model_dump(mode="json"), "methodology")
    methodology_digest = _sha256(methodology_data)
    methodology_path = f"/data/v1/methodology.{methodology_digest}.json"
    assets[methodology_path] = methodology_data

    manifest = Manifest(
        schema_version="1.0",
        release_id=release_id,
        published_at=published_at,
        label=label,
        data_kind=data_kind,
        report_count=len(manifest_reports),
        reports=manifest_reports,
        models=AssetReference(
            path=models_path,
            sha256=models_digest,
            size=len(models_data),
        ),
        methodology=AssetReference(
            path=methodology_path,
            sha256=methodology_digest,
            size=len(methodology_data),
        ),
        limits=ReleaseLimits(
            max_reports=MAX_REPORTS,
            max_files=MAX_FILES,
            max_asset_bytes=MAX_ASSET_BYTES,
        ),
    )
    assets["/data/v1/manifest.json"] = _json_bytes(manifest.model_dump(mode="json"))
    return manifest, assets


def _verify_release(target: Path, manifest: Manifest, assets: dict[str, bytes]) -> None:
    files = [path for path in target.rglob("*") if path.is_file()]
    if len(files) > MAX_FILES:
        raise PublicationError(f"A release may contain at most {MAX_FILES} files")
    expected = {"/data/v1/manifest.json"} | set(assets)
    actual = {"/data/v1/" + path.relative_to(target).as_posix() for path in files}
    if actual != expected:
        raise PublicationError("Staged release contains missing or unexpected files")
    for path in files:
        if path.stat().st_size > MAX_ASSET_BYTES:
            raise PublicationError(f"{path.name} exceeds the public asset size limit")
    for public_path, expected_bytes in assets.items():
        relative = public_path.removeprefix("/data/v1/")
        path = target / relative
        data = path.read_bytes()
        if data != expected_bytes:
            raise PublicationError(f"{public_path} changed after staging")
        if _sha256(data) != _sha256(expected_bytes):
            raise PublicationError(f"{public_path} checksum mismatch")
    manifest_data = (target / "manifest.json").read_bytes()
    parsed = Manifest.model_validate_json(manifest_data)
    if parsed.model_dump(mode="json") != manifest.model_dump(mode="json"):
        raise PublicationError("Manifest changed after staging")
    for entry in manifest.reports:
        relative = entry.path.removeprefix("/data/v1/")
        report = PublishedReport.model_validate_json((target / relative).read_bytes())
        if report.id != entry.id or _sha256((target / relative).read_bytes()) != entry.sha256:
            raise PublicationError(f"Report {entry.id!r} does not match the manifest")
    models = ModelsSnapshot.model_validate_json(
        (target / manifest.models.path.removeprefix("/data/v1/")).read_bytes()
    )
    if _sha256((target / manifest.models.path.removeprefix("/data/v1/")).read_bytes()) != (
        manifest.models.sha256
    ):
        raise PublicationError("Models asset checksum mismatch")
    if len(models.models) != len({model.id for model in models.models}):
        raise PublicationError("Models asset contains duplicate identifiers")
    MethodologySnapshot.model_validate_json(
        (target / manifest.methodology.path.removeprefix("/data/v1/")).read_bytes()
    )


def _write_release(target: Path, assets: dict[str, bytes]) -> None:
    for public_path, data in assets.items():
        relative = public_path.removeprefix("/data/v1/")
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _replace_release(output: Path, staging: Path) -> None:
    target = output / "v1"
    backup = output / f".v1-backup-{staging.name}"
    moved = False
    try:
        if target.exists():
            target.rename(backup)
            moved = True
        staging.rename(target)
    except Exception:
        if moved and backup.exists() and not target.exists():
            backup.rename(target)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)


def publish_reports(
    reports: Sequence[PublishedReport],
    output: Path,
    *,
    release_id: str,
    published_at: datetime,
    dry_run: bool = False,
) -> Manifest:
    if published_at.utcoffset() is None:
        raise PublicationError("Release timestamp must be timezone-aware")
    manifest, assets = _build_release(reports, release_id, published_at)
    if dry_run:
        with tempfile.TemporaryDirectory() as directory:
            staging = Path(directory) / "v1"
            staging.mkdir()
            _write_release(staging, assets)
            _verify_release(staging, manifest, assets)
        return manifest
    output.mkdir(parents=True, exist_ok=True)
    staging = output / f".v1-{release_id}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        _write_release(staging, assets)
        _verify_release(staging, manifest, assets)
        _replace_release(output, staging)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest


def load_reports_from_fixture(path: Path) -> list[PublishedReport]:
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PublicationError(f"Cannot read report fixture: {error}") from error
    items: Any = data
    if isinstance(data, dict):
        reports = data.get("reports")
        if isinstance(reports, dict):
            items = reports.get("data")
        elif isinstance(reports, list):
            items = reports
        else:
            items = data.get("items")
    if not isinstance(items, list):
        raise PublicationError("Report fixture must contain a list of published reports")
    try:
        return [PublishedReport.model_validate(item) for item in items]
    except ValidationError as error:
        raise PublicationError(f"Report fixture failed validation: {error}") from error


def load_reports_from_database(database_url: str | None = None) -> list[PublishedReport]:
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as session:
            rows = list(
                session.scalars(
                    sa.select(PublishedReportRow).order_by(
                        PublishedReportRow.published_at.desc(),
                        PublishedReportRow.id,
                    )
                )
            )
            reports: list[PublishedReport] = []
            for row in rows:
                report = PublishedReport.model_validate(row.payload)
                if report.id != row.id or report.summary.experiment_id != row.experiment_id:
                    raise PublicationError(f"Stored report {row.id!r} has inconsistent identifiers")
                if report.published_at != row.published_at:
                    raise PublicationError(
                        f"Stored report {row.id!r} has an inconsistent timestamp"
                    )
                if report_payload_sha256(row.payload) != row.payload_sha256:
                    raise PublicationError(f"Stored report {row.id!r} failed its checksum")
                reports.append(report)
            return reports
    finally:
        engine.dispose()


def _timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected an ISO-8601 timestamp") from error
    if parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("Timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def _default_release_id(published_at: datetime, reports: Sequence[PublishedReport]) -> str:
    digest = _sha256(
        _json_bytes([report_payload_sha256(report.model_dump(mode="json")) for report in reports])
    )[:8]
    return f"REL-{published_at.strftime('%Y%m%dT%H%M%SZ')}-{digest}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate reviewed reports and publish immutable static snapshots."
    )
    parser.add_argument("--database-url", default=None, help="SQLAlchemy database URL")
    parser.add_argument("--fixture", type=Path, default=None, help="Reviewed report JSON fixture")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("apps/web/public/data"),
        help="Static data root; writes v1/manifest.json beneath it",
    )
    parser.add_argument("--release-id", default=None, help="Stable release identifier")
    parser.add_argument("--published-at", type=_timestamp, default=None, help="Release timestamp")
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate and stage in memory without replacing the public release",
    )
    args = parser.parse_args(argv)
    try:
        reports = (
            load_reports_from_fixture(args.fixture)
            if args.fixture is not None
            else load_reports_from_database(args.database_url)
        )
        published_at = args.published_at or datetime.now(UTC)
        release_id = args.release_id or _default_release_id(published_at, reports)
        manifest = publish_reports(
            reports,
            args.output,
            release_id=release_id,
            published_at=published_at,
            dry_run=args.validate_only,
        )
    except (PublicationError, ValidationError, OSError) as error:
        print(f"publish failed: {error}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "release_id": manifest.release_id,
                "published_at": manifest.published_at.isoformat().replace("+00:00", "Z"),
                "label": manifest.label,
                "report_count": manifest.report_count,
                "manifest": (args.output / "v1" / "manifest.json").as_posix(),
                "written": not args.validate_only,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
