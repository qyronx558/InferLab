"""Migration-driven CPU SQLite tests; PostgreSQL DDL checks require no server."""

import io
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session

from inferlab_api.database.models import (
    AuditEvent,
    Base,
    Experiment,
    Job,
    ModelRegistry,
    PublishedReport,
    RunMetric,
    published_report_runs,
    report_payload_sha256,
)
from inferlab_api.database.session import create_database_engine, database_url, session_factory

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


def migration_config(url: str) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url  # Bypasses INI percent interpolation safely.
    return config


@pytest.fixture
def migrated(tmp_path: Path) -> Iterator[Engine]:
    url = "sqlite:///" + (tmp_path / "inferlab.db").as_posix()
    command.upgrade(migration_config(url), "head")
    engine = create_database_engine(url)
    try:
        yield engine
    finally:
        engine.dispose()


def add_experiment(session: Session, identifier: str = "EXP-db") -> None:
    if session.get(ModelRegistry, "model-demo") is None:
        session.add(
            ModelRegistry(
                id="model-demo",
                name="DEMO MODEL",
                revision="demo-revision",
                sha256="a" * 64,
                quantization="Q4_K_M",
                max_context_tokens=8192,
                license_name="Synthetic fixture",
                created_at=NOW,
            )
        )
        session.flush()
    session.add(
        Experiment(
            id=identifier,
            model_id="model-demo",
            model_revision="demo-revision",
            model_sha256="a" * 64,
            quantization="Q4_K_M",
            engine_id="llama.cpp",
            engine_version="demo",
            engine_build="demo-build",
            seed_supported=True,
            workload_id="synthetic-v1",
            workload_sha256="b" * 64,
            prompt_id="synthetic-prompt",
            condition="warm",
            context_tokens=2048,
            input_token_budget=512,
            max_output_tokens=128,
            temperature=0.0,
            top_p=1.0,
            seed=42,
            warmups=2,
            repetitions=8,
            concurrency=1,
            timeout_seconds=600,
            gpu_device_id="gpu-0",
            gpu_layers=8,
            device_name="DEMO DEVICE",
            driver_version="demo-driver",
            methodology_version="demo-v1",
            created_at=NOW,
        )
    )
    session.flush()


def job_values(identifier: str = "JOB-db", experiment_id: str = "EXP-db") -> dict[str, Any]:
    return dict(
        id=identifier,
        experiment_id=experiment_id,
        idempotency_key=identifier,
        request_sha256="c" * 64,
        phase="queued",
        attempt=0,
        cancellation_requested=False,
        created_at=NOW,
    )


def run_values(identifier: str = "RUN-db") -> dict[str, Any]:
    return dict(
        id=identifier,
        job_id="JOB-db",
        experiment_id="EXP-db",
        attempt=1,
        kind="measured",
        repetition=0,
        condition="warm",
        state="complete",
        recorded_at=NOW,
        input_tokens=10,
        output_tokens=0,
        ttft_ms=None,
        ttft_ms_reason="no_samples",
        request_latency_ms=0.0,
        request_latency_ms_reason=None,
        decode_tokens_per_second=None,
        decode_tokens_per_second_reason="unsupported",
        peak_vram_mib=None,
        peak_vram_mib_reason="not_measured",
        quality_score=None,
        quality_score_reason="not_measured",
    )


def add_run_parents(session: Session) -> None:
    add_experiment(session)
    session.add(Job(**job_values()))
    session.flush()


def report_values() -> dict[str, Any]:
    demo = json.loads((ROOT / "contracts/fixtures/demo.json").read_text("utf-8"))
    payload = demo["reports"]["data"][0]
    payload.update(id="REPORT-db", published_at=NOW.isoformat())
    payload["config"].update(
        experiment_id="EXP-db",
        model_id="model-demo",
        model_revision="demo-revision",
        model_sha256="a" * 64,
        engine_id="llama.cpp",
        engine_version="demo",
        engine_build="demo-build",
        max_output_tokens=128,
        repetitions=8,
        prompt_id="synthetic-prompt",
        gpu_layers=8,
    )
    provenance = payload["provenance"]
    provenance["engine"].update(id="llama.cpp", version="demo", build="demo-build")
    provenance["model"].update(
        id="model-demo", revision="demo-revision", sha256="a" * 64, engine_ids=["llama.cpp"]
    )
    provenance["workload"].update(sha256="b" * 64, prompt_id="synthetic-prompt")
    provenance["hardware"].update(
        device_name="DEMO DEVICE", driver_version="demo-driver", gpu_layers=8
    )
    run = payload["runs"][0]
    values = run_values()
    for key in (
        "id",
        "experiment_id",
        "attempt",
        "kind",
        "repetition",
        "condition",
        "state",
        "input_tokens",
        "output_tokens",
    ):
        run[key] = values[key]
    run["recorded_at"] = NOW.isoformat()
    for wire, column in {
        "ttft": "ttft_ms",
        "request_latency": "request_latency_ms",
        "decode_throughput": "decode_tokens_per_second",
        "peak_vram": "peak_vram_mib",
        "quality": "quality_score",
    }.items():
        run[wire].update(value=values[column], unavailable_reason=values[column + "_reason"])
    summary = payload["summary"]
    summary.update(experiment_id="EXP-db", accepted_run_ids=["RUN-db"])
    for summary_key, run_key in {
        "ttft_median": "ttft",
        "request_latency_p95": "request_latency",
        "decode_throughput": "decode_throughput",
        "peak_vram": "peak_vram",
        "quality": "quality",
    }.items():
        summary[summary_key] = dict(run[run_key])
    return dict(
        id="REPORT-db",
        experiment_id="EXP-db",
        payload=payload,
        payload_sha256=report_payload_sha256(payload),
        published_at=NOW,
    )


def test_migrations_upgrade_downgrade_reupgrade_and_metadata_match(tmp_path: Path) -> None:
    url = "sqlite:///" + (tmp_path / "cycle.db").as_posix()
    config = migration_config(url)
    command.upgrade(config, "head")
    command.upgrade(config, "head")  # Reapplying head is a no-op.
    engine = create_database_engine(url)
    try:
        assert set(sa.inspect(engine).get_table_names()) == set(Base.metadata.tables) | {
            "alembic_version"
        }
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={"compare_type": True})
            assert compare_metadata(context, Base.metadata) == []
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        with Session(engine) as session:
            add_run_parents(session)
            session.add(RunMetric(**run_values()))
            session.commit()
        command.downgrade(config, "base")
        assert sa.inspect(engine).get_table_names() == ["alembic_version"]
        command.upgrade(config, "head")
        assert set(Base.metadata.tables) <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_typed_units_missing_values_and_utc_round_trip(migrated: Engine) -> None:
    with session_factory(migrated)() as session:
        add_run_parents(session)
        values = run_values()
        values["recorded_at"] = NOW.astimezone(timezone(timedelta(hours=5, minutes=30)))
        session.add(RunMetric(**values))
        session.commit()
        session.expire_all()
        run = session.get(RunMetric, "RUN-db")
        assert run is not None and run.recorded_at == NOW and run.recorded_at.tzinfo == UTC
        assert run.request_latency_ms == 0.0 and run.request_latency_ms_reason is None
        assert run.peak_vram_mib is None and run.peak_vram_mib_reason == "not_measured"
        assert run.output_tokens == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("output_tokens", -1),
        ("attempt", 0),
        ("repetition", 20),
        ("input_tokens", None),
        ("condition", "cold"),
        ("request_latency_ms_reason", "not_measured"),
        ("ttft_ms_reason", None),
        ("quality_score", 2.0),
        ("error_code", "timeout"),
        ("trace_sha256", "e" * 64),
        ("job_id", "JOB-missing"),
    ],
)
def test_run_database_constraints_reject_invalid_rows(
    migrated: Engine, field: str, value: object
) -> None:
    with Session(migrated) as session:
        add_run_parents(session)
        values = run_values()
        values[field] = value
        session.add(RunMetric(**values))
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0, True, "123"])
def test_measurements_do_not_accept_nonfinite_coerced_or_negative_values(
    migrated: Engine, value: object
) -> None:
    with Session(migrated) as session:
        add_run_parents(session)
        values = run_values()
        values["request_latency_ms"] = value
        session.add(RunMetric(**values))
        with pytest.raises(StatementError):
            session.flush()


def test_duplicate_run_identity_and_cross_experiment_job_are_rejected(migrated: Engine) -> None:
    with Session(migrated) as session:
        add_run_parents(session)
        session.add(RunMetric(**run_values()))
        session.commit()
        duplicate = run_values("RUN-duplicate")
        session.add(RunMetric(**duplicate))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        add_experiment(session, "EXP-other")
        values = run_values("RUN-cross-experiment")
        values["experiment_id"] = "EXP-other"
        session.add(RunMetric(**values))
        with pytest.raises(IntegrityError):
            session.flush()


def test_idempotency_and_single_active_job(migrated: Engine) -> None:
    with Session(migrated) as session:
        add_experiment(session)
        active = job_values()
        active.update(
            phase="running",
            attempt=1,
            active_slot=1,
            worker_id="worker-demo",
            fencing_token=1,
            lease_expires_at=NOW + timedelta(seconds=120),
            started_at=NOW,
        )
        session.add(Job(**active))
        session.commit()
        second = {**active, "id": "JOB-other", "idempotency_key": "JOB-other"}
        session.add(Job(**second))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
        second.update(
            phase="queued", active_slot=None, lease_expires_at=None, idempotency_key="JOB-db"
        )
        session.add(Job(**second))
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize("mutation", ["budget", "cold-warmups", "seed", "concurrency", "model-pin"])
def test_experiment_constraints_and_pinned_registry_reference(
    migrated: Engine, mutation: str
) -> None:
    with Session(migrated) as session:
        add_experiment(session)
        experiment = session.get(Experiment, "EXP-db")
        assert experiment is not None
        if mutation == "budget":
            experiment.context_tokens = 128
        elif mutation == "cold-warmups":
            experiment.condition = "cold"
        elif mutation == "seed":
            experiment.seed_supported = False
        elif mutation == "concurrency":
            experiment.concurrency = 2
        else:
            experiment.model_sha256 = "f" * 64
        with pytest.raises(IntegrityError):
            session.flush()


def test_report_evidence_prevents_deletion_and_cross_experiment_links(migrated: Engine) -> None:
    with Session(migrated) as session:
        add_run_parents(session)
        session.add(RunMetric(**run_values()))
        session.flush()
        job = session.get(Job, "JOB-db")
        assert job is not None
        job.phase, job.attempt, job.started_at, job.finished_at = "completed", 1, NOW, NOW
        session.flush()
        session.add(PublishedReport(**report_values()))
        session.flush()
        session.commit()
        with pytest.raises(IntegrityError):
            session.execute(sa.delete(RunMetric).where(RunMetric.id == "RUN-db"))
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(sa.delete(Experiment).where(Experiment.id == "EXP-db"))
        session.rollback()
        with pytest.raises(IntegrityError):
            session.execute(
                sa.insert(published_report_runs).values(
                    report_id="REPORT-db", run_id="RUN-db", experiment_id="EXP-unrelated"
                )
            )


def test_privacy_surface_and_snapshot_extra_fields(migrated: Engine) -> None:
    forbidden = {
        "prompt",
        "raw_prompt",
        "response_text",
        "trace",
        "artifact_path",
        "password",
        "message",
    }
    assert all(
        not forbidden.intersection(table.columns.keys()) for table in Base.metadata.tables.values()
    )
    with pytest.raises(TypeError):
        Experiment(raw_prompt="personal prompt")
    with Session(migrated) as session:
        add_experiment(session)
        values = report_values()
        values["payload"]["raw_prompt"] = "personal prompt"
        session.add(PublishedReport(**values))
        with pytest.raises((ValueError, StatementError)):
            session.flush()


def test_audit_and_indexes_for_queue_retention_and_reports(migrated: Engine) -> None:
    with Session(migrated) as session:
        session.add(
            AuditEvent(
                id="AUDIT-demo",
                recorded_at=NOW,
                actor="system",
                action="retention",
                outcome="success",
                subject_type="system",
                subject_id="local",
            )
        )
        session.commit()
    inspector = sa.inspect(migrated)
    for table, names in {
        "jobs": {"ix_jobs_queue", "ix_jobs_lease_expiry", "ix_jobs_experiment"},
        "run_metrics": {"ix_runs_experiment_state", "ix_runs_trace_expiry"},
        "audit_events": {"ix_audit_retention", "ix_audit_subject"},
        "published_reports": {"ix_reports_experiment_published"},
    }.items():
        assert names <= {index["name"] for index in inspector.get_indexes(table)}


def test_naive_dates_and_invalid_identifiers_rejected(migrated: Engine) -> None:
    with Session(migrated) as session:
        session.add(
            AuditEvent(
                id="AUDIT-demo",
                recorded_at=NOW.replace(tzinfo=None),
                actor="admin",
                action="login",
                outcome="failure",
                subject_type="system",
                subject_id="local",
            )
        )
        with pytest.raises(StatementError):
            session.flush()
        session.rollback()
        session.add(
            ModelRegistry(
                id="../unsafe",
                name="demo",
                revision="demo",
                sha256="z" * 64,
                quantization="Q4_K_M",
                max_context_tokens=2048,
                license_name="demo",
            )
        )
        with pytest.raises(StatementError):
            session.flush()


def test_postgresql_offline_upgrade_and_downgrade_sql_without_server() -> None:
    config = migration_config("postgresql+psycopg://placeholder:placeholder@127.0.0.1/inferlab")
    config.output_buffer = io.StringIO()
    command.upgrade(config, "head", sql=True)
    sql = config.output_buffer.getvalue()
    assert "CREATE TABLE model_registry" in sql and "CREATE TABLE run_metrics" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql and "PRAGMA" not in sql
    assert "placeholder" not in sql
    config.output_buffer = io.StringIO()
    command.downgrade(config, "head:base", sql=True)
    assert "DROP TABLE model_registry" in config.output_buffer.getvalue()


def test_database_url_environment_and_redacted_render(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INFERLAB_DATABASE_URL", "postgresql://user:secret%25@localhost/inferlab")
    url = database_url()
    assert url.drivername == "postgresql+psycopg" and url.password == "secret%"
    assert "secret" not in str(url)
    assert database_url("sqlite:///:memory:").get_backend_name() == "sqlite"
    with pytest.raises(ValueError):
        database_url("mysql://localhost/inferlab")


def add_publishable_evidence(session: Session) -> None:
    add_run_parents(session)
    session.add(RunMetric(**run_values()))
    job = session.get(Job, "JOB-db")
    assert job is not None
    job.phase, job.attempt, job.started_at, job.finished_at = "completed", 1, NOW, NOW
    session.commit()


@pytest.mark.parametrize(
    "mutation", ["row-id", "hash", "config", "run-value", "unknown-run", "job-not-complete"]
)
def test_report_snapshot_must_match_real_relational_evidence(
    migrated: Engine, mutation: str
) -> None:
    with Session(migrated) as session:
        add_publishable_evidence(session)
        values = report_values()
        if mutation == "row-id":
            values["id"] = "REPORT-other"
        elif mutation == "hash":
            values["payload_sha256"] = "f" * 64
        elif mutation == "config":
            values["payload"]["config"]["repetitions"] = 7
            values["payload_sha256"] = report_payload_sha256(values["payload"])
        elif mutation == "run-value":
            values["payload"]["runs"][0]["request_latency"]["value"] = 1.0
            values["payload_sha256"] = report_payload_sha256(values["payload"])
        elif mutation == "unknown-run":
            values["payload"]["runs"][0]["id"] = "RUN-missing"
            values["payload"]["summary"]["accepted_run_ids"] = ["RUN-missing"]
            values["payload_sha256"] = report_payload_sha256(values["payload"])
        else:
            job = session.get(Job, "JOB-db")
            assert job is not None
            job.phase, job.finished_at = "queued", None
            session.flush()
        session.add(PublishedReport(**values))
        with pytest.raises(ValueError):
            session.flush()
        session.rollback()
        assert session.scalar(sa.select(sa.func.count()).select_from(published_report_runs)) == 0


def test_report_links_are_atomic_and_report_snapshots_are_immutable(migrated: Engine) -> None:
    with Session(migrated) as session:
        add_publishable_evidence(session)
        report = PublishedReport(**report_values())
        session.add(report)
        session.flush()
        assert session.scalar(sa.select(sa.func.count()).select_from(published_report_runs)) == 1
        session.rollback()
        assert session.scalar(sa.select(sa.func.count()).select_from(published_report_runs)) == 0
        session.add(PublishedReport(**report_values()))
        session.commit()
        stored_report = session.get(PublishedReport, "REPORT-db")
        assert stored_report is not None
        stored_report.published_at = NOW + timedelta(seconds=1)
        with pytest.raises(ValueError, match="immutable"):
            session.flush()


def test_registry_pin_cannot_change_under_an_existing_experiment(migrated: Engine) -> None:
    with Session(migrated) as session:
        add_experiment(session)
        session.commit()
        model = session.get(ModelRegistry, "model-demo")
        assert model is not None
        model.sha256 = "f" * 64
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize("mutation", ["slot", "lease", "start", "fence", "cancelled-completion"])
def test_job_lifecycle_constraints(migrated: Engine, mutation: str) -> None:
    with Session(migrated) as session:
        add_experiment(session)
        values = job_values()
        values.update(
            phase="running",
            attempt=1,
            active_slot=1,
            started_at=NOW,
            worker_id="worker-demo",
            fencing_token=1,
            lease_expires_at=NOW + timedelta(seconds=120),
        )
        if mutation == "slot":
            values["active_slot"] = None
        elif mutation == "lease":
            values["lease_expires_at"] = None
        elif mutation == "start":
            values["started_at"] = None
        elif mutation == "fence":
            values["fencing_token"] = 0
        else:
            values.update(
                phase="completed",
                active_slot=None,
                lease_expires_at=None,
                finished_at=NOW,
                cancellation_requested=True,
            )
        session.add(Job(**values))
        with pytest.raises(IntegrityError):
            session.flush()


@pytest.mark.parametrize("entity", ["run", "experiment"])
def test_published_source_evidence_cannot_be_edited_through_orm(
    migrated: Engine, entity: str
) -> None:
    with Session(migrated) as session:
        add_publishable_evidence(session)
        session.add(PublishedReport(**report_values()))
        session.commit()
        if entity == "run":
            run = session.get(RunMetric, "RUN-db")
            assert run is not None
            run.request_latency_ms = 1.0
        else:
            experiment = session.get(Experiment, "EXP-db")
            assert experiment is not None
            experiment.engine_build = "changed-build"
        with pytest.raises(ValueError, match="immutable"):
            session.flush()
