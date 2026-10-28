"""HTTP/database integration tests: CPU-only, injected admission, no model runtime."""

import copy
import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier
from typing import Any, cast

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from inferlab_api.contracts import ExperimentConfig, JobPhase, Provenance, Registry
from inferlab_api.database.models import (
    AdminSession,
    APIControl,
    APIRequest,
    AuditEvent,
    Experiment,
    Job,
    ModelRegistry,
    PublishedReport,
    RunMetric,
    WorkerControl,
    report_payload_sha256,
)
from inferlab_api.database.session import create_database_engine
from inferlab_api.dependencies import Settings
from inferlab_api.errors import APIError
from inferlab_api.lifecycle import TRANSITIONS, check_transition
from inferlab_api.main import create_app
from inferlab_api.security import COOKIE

ROOT = Path(__file__).resolve().parents[1]
DEMO: dict[str, Any] = json.loads((ROOT / "contracts/fixtures/demo.json").read_text("utf-8"))
PASSWORD = "test-only-password-never-a-production-credential"
ORIGIN = "https://127.0.0.1:5173"
BASE = "/api/v1"


class TestClock:
    __test__ = False
    value = datetime(2026, 10, 23, 12, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.value


class FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    def registry(self) -> Registry:
        return Registry.model_validate(DEMO["registry"]["data"])

    def resolve(self, config: ExperimentConfig) -> Provenance:
        self.calls += 1
        value = copy.deepcopy(DEMO["experiments"]["data"]["items"][0]["provenance"])
        registry = self.registry()
        value["engine"] = next(e.model_dump() for e in registry.engines if e.id == config.engine_id)
        value["model"] = next(m.model_dump() for m in registry.models if m.id == config.model_id)
        if config.gpu_device_id != value["hardware"]["gpu_device_id"]:
            raise ValueError("Unknown GPU")
        if config.gpu_layers is not None and config.gpu_layers > 32:
            raise ValueError("Operator GPU layer limit")
        value["hardware"]["gpu_layers"] = config.gpu_layers
        return Provenance.model_validate(value)


@dataclass
class APIHarness:
    client: TestClient
    engine: Engine
    clock: TestClock
    runner: FakeRunner
    headers: dict[str, str]

    def body(self, identifier: str = "EXP-api", key: str = "submit-api") -> dict[str, Any]:
        config = copy.deepcopy(DEMO["experiments"]["data"]["items"][0]["config"])
        config["experiment_id"] = identifier
        return {"name": "DEMO DATA integration test", "idempotency_key": key, "config": config}

    def submit(self, identifier: str = "EXP-api", key: str = "submit-api") -> Any:
        return self.client.post(
            BASE + "/experiments",
            json=self.body(identifier, key),
            headers=self.headers | {"Idempotency-Key": key},
        )

    def mutate(self, method: str, path: str, key: str, body: object = None) -> Any:
        return self.client.request(
            method, BASE + path, json=body, headers=self.headers | {"Idempotency-Key": key}
        )


@pytest.fixture(scope="session")
def password_hash() -> str:
    return PasswordHasher().hash(PASSWORD)


@pytest.fixture
def api(tmp_path: Path, password_hash: str) -> Iterator[APIHarness]:
    url = "sqlite:///" + (tmp_path / "api.db").as_posix()
    config = Config(str(ROOT / "alembic.ini"))
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_database_engine(url)
    clock, runner = TestClock(), FakeRunner()
    application = create_app(
        engine=engine,
        settings=Settings(origin=ORIGIN, password_hash=password_hash),
        runner=runner,
        clock=clock,
    )
    try:
        with TestClient(application, base_url="https://127.0.0.1") as client:
            login = client.post(
                BASE + "/auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
            )
            assert login.status_code == 200, login.text
            yield APIHarness(
                client,
                engine,
                clock,
                runner,
                {
                    "Origin": ORIGIN,
                    "X-CSRF-Token": login.json()["csrf_token"],
                },
            )
    finally:
        engine.dispose()


def set_phase(api: APIHarness, phase: str) -> str:
    with Session(api.engine) as session:
        job = session.scalars(sa.select(Job).where(Job.experiment_id == "EXP-api")).one()
        job.phase = phase
        if phase in {"leased", "running", "completed", "failed"}:
            job.attempt = 1
        if phase in {"leased", "running"}:
            job.active_slot = 1
            job.worker_id = "worker-test"
            job.fencing_token = 1
            job.lease_expires_at = api.clock() + timedelta(seconds=30)
        if phase in {"running", "completed"}:
            job.started_at = api.clock()
        if phase in {"completed", "failed", "cancelled"}:
            job.finished_at = api.clock()
        if phase in {"failed", "cancelled"}:
            job.error_code = "timeout" if phase == "failed" else "cancelled"
        session.commit()
        return job.id


def seed_report(api: APIHarness, identifier: str = "REPORT-public") -> dict[str, Any]:
    """Insert approved DEMO DATA through normal ORM evidence guards."""
    payload = copy.deepcopy(DEMO["reports"]["data"][0])
    payload["id"] = identifier
    config = ExperimentConfig.model_validate(payload["config"])
    provenance = Provenance.model_validate(payload["provenance"])
    with Session(api.engine) as session:
        if session.get(Experiment, config.experiment_id) is None:
            if session.get(ModelRegistry, config.model_id) is None:
                session.add(
                    ModelRegistry(
                        **provenance.model.model_dump(exclude={"parameter_size", "engine_ids"})
                    )
                )
                session.flush()
            values = config.model_dump(exclude={"experiment_id", "sampling"})
            values.update(config.sampling.model_dump())
            experiment = Experiment(
                id=config.experiment_id,
                **values,
                workload_sha256=provenance.workload.sha256,
                device_name=provenance.hardware.device_name,
                driver_version=provenance.hardware.driver_version,
                methodology_version=provenance.methodology_version,
            )
            session.add(experiment)
            session.flush()
            run_time = datetime.fromisoformat(
                payload["runs"][0]["recorded_at"].replace("Z", "+00:00")
            )
            job = Job(
                id="JOB-public",
                experiment_id=experiment.id,
                phase="completed",
                attempt=1,
                idempotency_key="seed-public",
                request_sha256="0" * 64,
                created_at=run_time,
                started_at=run_time,
                finished_at=run_time,
                cancellation_requested=False,
            )
            session.add(job)
            session.flush()
            for run in payload["runs"]:
                values = {
                    k: v
                    for k, v in run.items()
                    if k
                    not in {"ttft", "request_latency", "decode_throughput", "peak_vram", "quality"}
                }
                values["recorded_at"] = datetime.fromisoformat(
                    run["recorded_at"].replace("Z", "+00:00")
                )
                for wire, column in {
                    "ttft": "ttft_ms",
                    "request_latency": "request_latency_ms",
                    "decode_throughput": "decode_tokens_per_second",
                    "peak_vram": "peak_vram_mib",
                    "quality": "quality_score",
                }.items():
                    values[column] = run[wire]["value"]
                    values[column + "_reason"] = run[wire]["unavailable_reason"]
                session.add(RunMetric(**values, job_id=job.id))
            session.flush()
        session.add(
            PublishedReport(
                id=identifier,
                experiment_id=config.experiment_id,
                payload=payload,
                payload_sha256=report_payload_sha256(payload),
                published_at=datetime.fromisoformat(payload["published_at"].replace("Z", "+00:00")),
            )
        )
        session.commit()
    return cast(dict[str, Any], payload)


def test_public_views_only_published_snapshots(api: APIHarness) -> None:
    assert api.submit().status_code == 202
    api.client.cookies.clear()
    assert api.client.get(BASE + "/public/reports").json() == {"items": [], "next_cursor": None}
    assert api.client.get(BASE + "/public/metadata").json()["items"] == []
    payload = seed_report(api)
    response = api.client.get(BASE + "/public/reports/REPORT-public")
    assert response.status_code == 200
    assert response.json()["label"] == "DEMO DATA"
    assert response.json()["config"] == payload["config"]
    metadata = api.client.get(BASE + "/public/metadata").json()["items"][0]
    assert set(metadata) == {"report_id", "engine", "model", "methodology_version"}
    assert "EXP-api" not in json.dumps(metadata)
    assert api.client.get(BASE + "/public/reports/EXP-api").status_code == 404


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("GET", "/registry", None),
        ("GET", "/worker", None),
        ("GET", "/experiments", None),
        ("GET", "/experiments/EXP-api", None),
        ("POST", "/experiments", {}),
        ("PATCH", "/experiments/EXP-api", {"name": "new", "expected_version": 1}),
        ("DELETE", "/experiments/EXP-api", {"expected_version": 1}),
        ("POST", "/experiments/EXP-api/cancel", None),
        ("POST", "/experiments/EXP-api/retry", None),
    ],
)
def test_private_routes_deny_public(api: APIHarness, method: str, path: str, body: object) -> None:
    api.client.cookies.clear()
    response = api.client.request(method, BASE + path, json=body)
    assert response.status_code == 401


def test_worker_status_uses_durable_heartbeat_without_claiming_execution(
    api: APIHarness,
) -> None:
    unknown = api.client.get(BASE + "/worker")
    assert unknown.status_code == 200
    assert unknown.json() == {
        "availability": "unknown",
        "worker_id": "unknown",
        "observed_at": "2026-10-23T12:00:00Z",
        "last_seen_at": None,
        "mode": None,
        "active_job_id": None,
        "paused": False,
    }

    assert api.submit().status_code == 202
    job_id = set_phase(api, "running")
    with Session(api.engine) as session:
        control = session.get(WorkerControl, 1)
        assert control is not None
        control.worker_id = "worker-test"
        control.last_heartbeat_at = api.clock() - timedelta(seconds=10)
        session.commit()

    online = api.client.get(BASE + "/worker")
    assert online.status_code == 200
    assert online.json()["availability"] == "online"
    assert online.json()["worker_id"] == "worker-test"
    assert online.json()["mode"] == "running"
    assert online.json()["active_job_id"] == job_id
    assert online.json()["paused"] is False

    with Session(api.engine) as session:
        control = session.get(WorkerControl, 1)
        assert control is not None
        control.paused = True
        control.last_heartbeat_at = api.clock() - timedelta(seconds=91)
        session.commit()

    offline = api.client.get(BASE + "/worker")
    assert offline.status_code == 200
    assert offline.json()["availability"] == "offline"
    assert offline.json()["last_seen_at"] == "2026-10-23T11:58:29Z"
    assert offline.json()["mode"] is None
    assert offline.json()["active_job_id"] is None
    assert offline.json()["paused"] is True


def test_crud_versions_archive_and_idempotency(api: APIHarness) -> None:
    created = api.submit()
    assert created.status_code == 202, created.text
    assert created.json()["job"]["phase"] == "queued"
    assert api.submit().json() == created.json()
    assert api.runner.calls == 1
    assert api.client.get(BASE + "/experiments/EXP-api").json() == created.json()
    renamed = api.mutate(
        "PATCH", "/experiments/EXP-api", "rename", {"name": "New name", "expected_version": 1}
    )
    assert renamed.status_code == 200
    assert renamed.json()["version"] == 2
    assert (
        api.mutate(
            "PATCH", "/experiments/EXP-api", "rename", {"name": "New name", "expected_version": 1}
        ).json()
        == renamed.json()
    )
    stale = api.mutate(
        "PATCH", "/experiments/EXP-api", "stale", {"name": "Stale", "expected_version": 1}
    )
    assert stale.status_code == 409
    deleted = api.mutate("DELETE", "/experiments/EXP-api", "archive", {"expected_version": 2})
    assert deleted.status_code == 200
    assert deleted.json()["archived_at"] is not None
    assert deleted.json()["job"]["phase"] == "cancelled"
    assert api.client.get(BASE + "/experiments/EXP-api").status_code == 404
    assert api.client.get(BASE + "/experiments").json()["items"] == []
    assert (
        api.mutate("DELETE", "/experiments/EXP-api", "archive", {"expected_version": 2}).json()
        == deleted.json()
    )
    assert api.submit().json() == created.json()  # Tombstone survives archive.
    assert api.submit(key="another-key").status_code == 409
    with Session(api.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Experiment)) == 1
        actions = list(
            session.scalars(sa.select(AuditEvent.action).where(AuditEvent.outcome == "success"))
        )
        assert sorted(actions) == ["delete", "login", "submit", "update"]


def test_idempotency_collision_and_restart(api: APIHarness, password_hash: str) -> None:
    original = api.submit()
    body = api.body()
    body["name"] = "Changed"
    assert (
        api.client.post(
            BASE + "/experiments",
            json=body,
            headers=api.headers | {"Idempotency-Key": "submit-api"},
        ).status_code
        == 409
    )
    # New app shares persistent sessions, limits and idempotency records; runner is offline.
    new_app = create_app(
        engine=api.engine, settings=Settings(ORIGIN, password_hash), clock=api.clock
    )
    with TestClient(new_app, base_url="https://127.0.0.1") as client:
        client.cookies.update(api.client.cookies)
        replayed = client.post(
            BASE + "/experiments",
            json=api.body(),
            headers=api.headers | {"Idempotency-Key": "submit-api"},
        )
        assert replayed.status_code == 202
        assert replayed.json() == original.json()
        assert (
            client.post(
                BASE + "/experiments",
                json=api.body("EXP-other", "other"),
                headers=api.headers | {"Idempotency-Key": "other"},
            ).status_code
            == 503
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("concurrency", 2),
        ("repetitions", 21),
        ("warmups", 6),
        ("timeout_seconds", 3601),
        ("context_tokens", 8193),
        ("max_output_tokens", 2049),
        ("gpu_layers", -1),
        ("gpu_layers", 201),
        ("gpu_device_id", "../../device"),
        ("model_id", "unapproved"),
        ("model_sha256", "f" * 64),
        ("gpu_layers", 33),
        ("gpu_device_id", "unknown-gpu"),
        ("concurrency", True),
        ("engine_version", "unapproved-build"),
    ],
)
def test_bounded_approved_configs(api: APIHarness, field: str, value: object) -> None:
    body = api.body()
    body["config"][field] = value
    response = api.client.post(
        BASE + "/experiments", json=body, headers=api.headers | {"Idempotency-Key": "submit-api"}
    )
    assert response.status_code == 422, response.text
    with Session(api.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Experiment)) == 0


@pytest.mark.parametrize(
    "field", ["command", "shell", "file_path", "model_url", "download", "prompt"]
)
def test_unsafe_inputs_are_forbidden(api: APIHarness, field: str) -> None:
    body = api.body()
    body["config"][field] = "private-canary-do-not-echo"
    response = api.client.post(
        BASE + "/experiments", json=body, headers=api.headers | {"Idempotency-Key": "submit-api"}
    )
    assert response.status_code == 422
    assert "private-canary" not in response.text
    assert response.json()["error"]["request_id"] == response.headers["x-request-id"]


@pytest.mark.parametrize(
    "phase", ["queued", "leased", "running", "completed", "failed", "cancelled"]
)
def test_cancellation_and_archive_phase_rules(api: APIHarness, phase: str) -> None:
    assert api.submit().status_code == 202
    set_phase(api, phase)
    response = api.mutate("POST", "/experiments/EXP-api/cancel", "cancel")
    if phase in {"completed", "failed"}:
        assert response.status_code == 409
    else:
        assert response.status_code == 200, response.text
        assert response.json()["job"]["phase"] == ("cancelled" if phase == "queued" else phase)
        if phase in {"leased", "running"}:
            assert response.json()["job"]["cancellation_requested"] is True
            assert response.json()["job"]["finished_at"] is None
    archived = api.mutate("DELETE", "/experiments/EXP-api", "archive", {"expected_version": 1})
    assert archived.status_code == (409 if phase in {"leased", "running"} else 200)


@pytest.mark.parametrize(
    "phase", ["queued", "leased", "running", "completed", "failed", "cancelled"]
)
def test_retry_creates_new_job_only_for_retryable_terminal_state(
    api: APIHarness, phase: str
) -> None:
    assert api.submit().status_code == 202
    old_id = set_phase(api, phase)
    response = api.mutate("POST", "/experiments/EXP-api/retry", "retry")
    if phase not in {"failed", "cancelled"}:
        assert response.status_code == 409
        return
    assert response.status_code == 202, response.text
    assert response.json()["job"]["id"] != old_id
    assert response.json()["job"]["phase"] == "queued"
    assert api.mutate("POST", "/experiments/EXP-api/retry", "retry").json() == response.json()
    with Session(api.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Job)) == 2
        old = session.get(Job, old_id)
        assert old is not None and old.phase == phase


def test_admin_and_public_cursor_pagination(api: APIHarness) -> None:
    for suffix in ("c", "a", "b"):
        assert api.submit("EXP-" + suffix, "key-" + suffix).status_code == 202
    first = api.client.get(BASE + "/experiments?limit=2").json()
    assert [item["id"] for item in first["items"]] == ["EXP-a", "EXP-b"]
    second = api.client.get(
        BASE + "/experiments", params={"limit": 2, "cursor": first["next_cursor"]}
    ).json()
    assert [item["id"] for item in second["items"]] == ["EXP-c"]
    assert second["next_cursor"] is None
    seed_report(api, "REPORT-a")
    seed_report(api, "REPORT-b")
    api.client.cookies.clear()
    for path in ("/public/reports", "/public/metadata"):
        first = api.client.get(BASE + path, params={"limit": 1}).json()
        assert first["next_cursor"] == "REPORT-a"
        second = api.client.get(
            BASE + path, params={"limit": 1, "cursor": first["next_cursor"]}
        ).json()
        assert len(second["items"]) == 1 and second["next_cursor"] is None
        for params in ({"limit": 101}, {"limit": 0}, {"cursor": "../../private"}):
            assert api.client.get(BASE + path, params=params).status_code == 422


def test_login_csrf_logout_expiry_and_cookie_flags(api: APIHarness) -> None:
    session_info = api.client.get(BASE + "/auth/session")
    assert session_info.status_code == 200
    assert session_info.json()["identity"] == "admin"
    assert (
        api.client.post(
            BASE + "/experiments", json=api.body(), headers={"Idempotency-Key": "submit-api"}
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            BASE + "/experiments",
            json=api.body(),
            headers=api.headers
            | {"Origin": "https://evil.example", "Idempotency-Key": "submit-api"},
        ).status_code
        == 403
    )
    assert (
        api.client.post(
            BASE + "/experiments",
            json=api.body(),
            headers=api.headers | {"X-CSRF-Token": "wrong", "Idempotency-Key": "submit-api"},
        ).status_code
        == 403
    )
    response = api.client.post(
        BASE + "/auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
    )
    flags = response.headers["set-cookie"].lower()
    assert all(
        flag in flags
        for flag in ("secure", "httponly", "samesite=strict", "path=/", "max-age=43200")
    )
    assert "domain=" not in flags
    api.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    assert api.client.post(BASE + "/auth/logout", headers=api.headers).status_code == 204
    assert api.client.get(BASE + "/auth/session").status_code == 401
    response = api.client.post(
        BASE + "/auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
    )
    assert response.status_code == 200
    api.clock.value += timedelta(hours=12)
    assert api.client.get(BASE + "/auth/session").status_code == 401
    with Session(api.engine) as session:
        stored = session.scalars(sa.select(AdminSession)).one()
        assert stored.token_sha256 != api.client.cookies.get(COOKIE)


def test_credential_rotation_revokes_existing_sessions(api: APIHarness) -> None:
    old_token = api.client.cookies.get(COOKIE)
    assert old_token is not None
    rotated_password = "rotated-password-never-a-production-credential"
    rotated_hash = PasswordHasher().hash(rotated_password)
    rotated = create_app(
        engine=api.engine,
        settings=Settings(origin=ORIGIN, password_hash=rotated_hash),
        runner=api.runner,
        clock=api.clock,
    )
    with TestClient(rotated, base_url="https://127.0.0.1") as client:
        stale = client.get(BASE + "/auth/session", headers={"Cookie": f"{COOKIE}={old_token}"})
        assert stale.status_code == 401
        assert (
            client.post(
                BASE + "/auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
            ).status_code
            == 401
        )
        login = client.post(
            BASE + "/auth/login",
            json={"password": rotated_password},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200
        assert client.get(BASE + "/auth/session").status_code == 200


def test_unconfigured_auth_fails_closed(api: APIHarness) -> None:
    token = api.client.cookies.get(COOKIE)
    assert token is not None
    application = create_app(engine=api.engine, settings=Settings(origin=ORIGIN), clock=api.clock)
    with TestClient(application, base_url="https://127.0.0.1") as client:
        response = client.get(BASE + "/auth/session", headers={"Cookie": f"{COOKIE}={token}"})
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "auth_not_configured"


def test_cors_allowlist_and_security_headers(api: APIHarness) -> None:
    allowed = api.client.options(
        BASE + "/experiments",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-CSRF-Token, Idempotency-Key",
        },
    )
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == ORIGIN
    assert allowed.headers["access-control-allow-credentials"] == "true"
    denied = api.client.options(
        BASE + "/experiments",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
    health = api.client.get("/health")
    assert health.headers["cache-control"] == "no-store"
    assert health.headers["x-content-type-options"] == "nosniff"
    assert health.headers["x-request-id"]


def test_login_lockout_persists_and_no_credentials_are_audited(
    api: APIHarness, password_hash: str
) -> None:
    api.client.cookies.clear()
    for _ in range(5):
        response = api.client.post(
            BASE + "/auth/login",
            json={"password": "private-password-canary"},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 401
    new_app = create_app(
        engine=api.engine, settings=Settings(ORIGIN, password_hash), clock=api.clock
    )
    with TestClient(new_app, base_url="https://127.0.0.1") as client:
        assert (
            client.post(
                BASE + "/auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
            ).status_code
            == 429
        )
        api.clock.value += timedelta(minutes=15)
        assert (
            client.post(
                BASE + "/auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
            ).status_code
            == 200
        )
    with Session(api.engine) as session:
        events = session.execute(sa.select(AuditEvent.__table__)).mappings().all()
        assert "private-password-canary" not in str(events)
        assert PASSWORD not in str(events)
        assert sum(e["outcome"] == "failure" for e in events) == 5


def test_request_size_streaming_encoding_and_tls(api: APIHarness) -> None:
    response = api.client.post(BASE + "/auth/login", content=b"x" * 65537)
    assert response.status_code == 413

    def chunks() -> Iterator[bytes]:
        yield b"x" * 40000
        yield b"y" * 40000

    assert api.client.post(BASE + "/auth/login", content=chunks()).status_code == 413
    assert (
        api.client.post(
            BASE + "/auth/login", content=b"{}", headers={"Content-Encoding": "gzip"}
        ).status_code
        == 415
    )
    response = api.client.post(
        "http://127.0.0.1/api/v1/auth/login",
        json={"password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    assert response.status_code == 403
    assert api.client.get("/health", headers={"Host": "attacker.example"}).status_code == 400


def test_queue_daily_and_mutation_limits(api: APIHarness) -> None:
    for number in range(10):
        response = api.submit(f"EXP-{number}", f"key-{number}")
        assert response.status_code == 202, response.text
    assert api.submit("EXP-full", "full").status_code == 429
    # Cancel one pending item: daily submission bound still applies.
    assert api.mutate("POST", "/experiments/EXP-0/cancel", "cancel-0").status_code == 200
    assert api.submit("EXP-daily", "daily").status_code == 429
    # Isolate mutation limit without creating more jobs.
    for number in range(7):
        response = api.mutate(
            "PATCH",
            "/experiments/EXP-0",
            f"rename-{number}",
            {"name": f"Name {number}", "expected_version": number + 1},
        )
        assert response.status_code == 200, response.text
    assert (
        api.mutate(
            "PATCH", "/experiments/EXP-0", "limited", {"name": "Limited", "expected_version": 8}
        ).status_code
        == 429
    )
    api.clock.value += timedelta(minutes=1)
    assert (
        api.mutate(
            "PATCH", "/experiments/EXP-0", "limited", {"name": "Limited", "expected_version": 8}
        ).status_code
        == 200
    )
    api.clock.value += timedelta(days=1)
    # Log in again after session expiry; daily admissions use a rolling day.
    login = api.client.post(
        BASE + "/auth/login", json={"password": PASSWORD}, headers={"Origin": ORIGIN}
    )
    api.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    assert api.submit("EXP-next-day", "next-day").status_code == 202


@pytest.mark.parametrize("current", list(TRANSITIONS))
@pytest.mark.parametrize("target", list(TRANSITIONS))
def test_complete_transition_matrix(current: JobPhase, target: JobPhase) -> None:
    if target in TRANSITIONS[current]:
        check_transition(current, target)
    else:
        with pytest.raises(APIError) as error:
            check_transition(current, target)
        assert error.value.status == 409


def test_failed_transaction_has_no_partial_experiment_or_idempotency(api: APIHarness) -> None:
    # Force a pinned registry conflict after schema validation/admission.
    assert api.submit().status_code == 202
    with Session(api.engine) as session:
        registered = session.get(ModelRegistry, api.body()["config"]["model_id"])
        assert registered is not None
        registered.max_context_tokens = 4096
        session.commit()
    response = api.submit("EXP-rejected", "rejected")
    assert response.status_code == 409
    with Session(api.engine) as session:
        assert session.get(Experiment, "EXP-rejected") is None
        assert session.get(APIRequest, "rejected") is None
        control = session.get(APIControl, 1)
        assert control is not None and control.mutation_count == 2


def test_concurrent_duplicate_requests_do_not_duplicate_jobs(api: APIHarness) -> None:
    barrier = Barrier(2)

    def submit() -> int:
        with TestClient(api.client.app, base_url="https://127.0.0.1") as client:
            client.cookies.update(api.client.cookies)
            barrier.wait(timeout=10)
            response = client.post(
                BASE + "/experiments",
                json=api.body(),
                headers=api.headers | {"Idempotency-Key": "submit-api"},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _: submit(), range(2)))
    assert all(status in {202, 503} for status in statuses), statuses
    # SQLite may reject a contended read-to-write upgrade; retry the same key.
    replayed = api.submit()
    assert replayed.status_code == 202, replayed.text
    with Session(api.engine) as session:
        assert session.scalar(sa.select(sa.func.count()).select_from(Job)) == 1
        assert session.scalar(sa.select(sa.func.count()).select_from(APIRequest)) == 1
        assert (
            session.scalar(
                sa.select(sa.func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.action == "submit", AuditEvent.outcome == "success")
            )
            == 1
        )


def test_published_snapshot_survives_private_rename_and_archive(api: APIHarness) -> None:
    payload = seed_report(api)
    identifier = payload["config"]["experiment_id"]
    before = api.client.get(BASE + "/public/reports/REPORT-public").json()
    renamed = api.mutate(
        "PATCH",
        f"/experiments/{identifier}",
        "rename-published",
        {
            "name": "Private administrative label",
            "expected_version": 1,
        },
    )
    assert renamed.status_code == 200, renamed.text
    archived = api.mutate(
        "DELETE",
        f"/experiments/{identifier}",
        "archive-published",
        {
            "expected_version": 2,
        },
    )
    assert archived.status_code == 200, archived.text
    assert api.client.get(BASE + "/public/reports/REPORT-public").json() == before


def test_mutation_payloads_cannot_replace_config_or_assign_job_state(api: APIHarness) -> None:
    assert api.submit().status_code == 202
    for body in (
        {"config": api.body()["config"], "expected_version": 1, "name": "New"},
        {"phase": "completed", "expected_version": 1, "name": "New"},
    ):
        assert api.mutate("PATCH", "/experiments/EXP-api", "unsafe-update", body).status_code == 422
    assert (
        api.mutate(
            "POST", "/experiments/EXP-api/cancel", "unsafe-cancel", {"command": "unsafe"}
        ).status_code
        == 422
    )
    with Session(api.engine) as session:
        failures = list(
            session.scalars(sa.select(AuditEvent).where(AuditEvent.outcome == "failure"))
        )
        assert len(failures) == 3
        assert {event.action for event in failures} == {"update", "cancel"}
