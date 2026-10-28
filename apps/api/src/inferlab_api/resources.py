"""Transactional experiment CRUD and approved, published-only public projections."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta
from typing import Annotated, Any, Literal, cast

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from .contracts import (
    PHASE_STATES,
    ExperimentConfig,
    ExperimentSubmitRequest,
    Identifier,
    JobPhase,
    Registry,
    WorkerHeartbeat,
    _validate_provenance,
    validate_submission,
)
from .contracts import Job as JobContract
from .contracts import (
    PublishedReport as ReportContract,
)
from .database.models import (
    APIRequest,
    Experiment,
    ExperimentMetadata,
    Job,
    ModelRegistry,
    PublishedReport,
    WorkerControl,
)
from .dependencies import RunnerPort, get_runner
from .errors import APIError
from .http_contracts import (
    EmptyRequest,
    ExperimentPage,
    ExperimentResource,
    MetadataPage,
    PublicMetadata,
    RenameRequest,
    ReportPage,
    VersionRequest,
)
from .lifecycle import check_transition
from .security import DB, Admin, Clock, Mutation, audit

router = APIRouter(prefix="/api/v1")
Runner = Annotated[RunnerPort, Depends(get_runner)]
Key = Annotated[Identifier, Header(alias="Idempotency-Key")]
Limit = Annotated[int, Query(ge=1, le=100)]
Cursor = Annotated[Identifier | None, Query()]


def request_hash(request: Request, body: object) -> str:
    value = json.dumps(
        {"method": request.method, "path": request.url.path, "body": body},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(value.encode()).hexdigest()


def replay(session: Session, key: str, fingerprint: str) -> ExperimentResource | None:
    saved = session.get(APIRequest, key)
    if saved is None:
        return None
    if saved.request_sha256 != fingerprint:
        raise APIError(409, "idempotency_conflict", "This key belongs to a different request.")
    return ExperimentResource.model_validate(saved.response)


def save(
    session: Session, key: str, fingerprint: str, resource: ExperimentResource, status: int
) -> ExperimentResource:
    session.add(
        APIRequest(
            key=key,
            request_sha256=fingerprint,
            response=resource.model_dump(mode="json"),
            status_code=status,
        )
    )
    session.commit()
    return resource


def lookup(session: Session, identifier: str) -> tuple[Experiment, ExperimentMetadata | None]:
    experiment = session.get(Experiment, identifier)
    metadata = session.get(ExperimentMetadata, identifier)
    if experiment is None or (metadata is not None and metadata.archived_at is not None):
        raise APIError(404, "not_found", "Experiment not found.")
    return experiment, metadata


def latest_job(session: Session, identifier: str) -> Job:
    job = session.scalars(
        sa.select(Job)
        .where(Job.experiment_id == identifier)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .limit(1)
    ).first()
    if job is None:
        raise APIError(409, "incomplete_evidence", "Experiment has no associated job.")
    return job


def to_config(experiment: Experiment) -> ExperimentConfig:
    data = {
        field: getattr(experiment, field)
        for field in ExperimentConfig.model_fields
        if field not in {"experiment_id", "sampling"}
    }
    data.update(
        experiment_id=experiment.id,
        sampling={
            "temperature": experiment.temperature,
            "top_p": experiment.top_p,
            "seed": experiment.seed,
        },
    )
    return ExperimentConfig.model_validate(data)


def resource(
    session: Session, experiment: Experiment, metadata: ExperimentMetadata | None
) -> ExperimentResource:
    job = latest_job(session, experiment.id)
    return ExperimentResource(
        id=experiment.id,
        name=metadata.name if metadata else experiment.id,
        version=metadata.version if metadata else 1,
        archived_at=metadata.archived_at if metadata else None,
        config=to_config(experiment),
        job=JobContract.model_validate(
            {
                field: getattr(job, field)
                for field in JobContract.model_fields
                if field not in {"state"}
            }
            | {"state": PHASE_STATES[cast(JobPhase, job.phase)]}
        ),
    )


def ensure_capacity(session: Session, now: datetime) -> None:
    queued = session.scalar(
        sa.select(sa.func.count()).select_from(Job).where(Job.phase == "queued")
    )
    daily = session.scalar(
        sa.select(sa.func.count()).select_from(Job).where(Job.created_at >= now - timedelta(days=1))
    )
    if (queued or 0) >= 10 or (daily or 0) >= 10:
        raise APIError(429, "admission_limit", "Queue or daily submission limit reached.")


@router.get("/registry", response_model=Registry, tags=["admin"])
def registry(identity: Admin, runner: Runner) -> Registry:
    return runner.registry()


@router.get("/worker", response_model=WorkerHeartbeat, tags=["admin"])
def worker_status(identity: Admin, session: DB, now: Clock) -> WorkerHeartbeat:
    """Report the last durable heartbeat without claiming a live execution."""
    control = session.get(WorkerControl, 1)
    active = session.scalars(sa.select(Job).where(Job.active_slot == 1).limit(1)).first()
    last_seen = control.last_heartbeat_at if control is not None else None
    worker_id = (control.worker_id if control is not None else None) or "unknown"
    paused = bool(control.paused) if control is not None else False
    if last_seen is None:
        return WorkerHeartbeat(
            availability="unknown",
            worker_id=worker_id,
            observed_at=now,
            last_seen_at=None,
            mode=None,
            active_job_id=None,
            paused=paused,
        )

    online = (now - last_seen).total_seconds() <= 90
    mode: Literal["idle", "running"] | None = None
    active_job_id: str | None = None
    if online:
        mode = "running" if active is not None else "idle"
        active_job_id = active.id if active is not None else None
    return WorkerHeartbeat(
        availability="online" if online else "offline",
        worker_id=worker_id,
        observed_at=now,
        last_seen_at=last_seen,
        mode=mode,
        active_job_id=active_job_id,
        paused=paused,
    )


@router.post("/experiments", response_model=ExperimentResource, status_code=202, tags=["admin"])
def create_experiment(
    body: ExperimentSubmitRequest,
    request: Request,
    identity: Mutation,
    session: DB,
    now: Clock,
    key: Key,
    runner: Runner,
) -> ExperimentResource:
    if key != body.idempotency_key:
        raise APIError(
            422, "invalid_idempotency_key", "Header and body idempotency keys must match."
        )
    fingerprint = request_hash(request, body.model_dump(mode="json"))
    previous = replay(session, key, fingerprint)
    if previous is not None:
        return previous
    config = body.config
    if session.get(Experiment, config.experiment_id) is not None:
        raise APIError(409, "experiment_exists", "Experiment ID is already reserved.")
    ensure_capacity(session, now)
    try:
        approved = runner.registry()
        validate_submission(body, approved)
        provenance = runner.resolve(config)
        # Use the same pin/hardware validators as the existing result contracts.
        _validate_provenance(config, provenance)
    except ValueError:
        raise APIError(
            422, "unapproved_config", "Configuration is not approved for this local runner."
        ) from None
    registered = session.get(ModelRegistry, config.model_id)
    model = provenance.model
    if registered is None:
        session.add(
            ModelRegistry(
                **model.model_dump(exclude={"parameter_size", "engine_ids"}), created_at=now
            )
        )
        session.flush()
    elif any(
        getattr(registered, field) != getattr(model, field)
        for field in ("revision", "sha256", "quantization", "max_context_tokens")
    ):
        raise APIError(409, "registry_conflict", "Model ID is pinned to different local metadata.")
    values: dict[str, Any] = config.model_dump(exclude={"experiment_id", "sampling"})
    values.update(config.sampling.model_dump())
    experiment = Experiment(
        id=config.experiment_id,
        **values,
        workload_sha256=provenance.workload.sha256,
        device_name=provenance.hardware.device_name,
        driver_version=provenance.hardware.driver_version,
        methodology_version=provenance.methodology_version,
        created_at=now,
    )
    session.add(experiment)
    session.flush()
    metadata = ExperimentMetadata(experiment_id=experiment.id, name=body.name, version=1)
    session.add_all(
        [
            metadata,
            Job(
                id="JOB-" + secrets.token_hex(16),
                experiment_id=experiment.id,
                idempotency_key=key,
                request_sha256=fingerprint,
                phase="queued",
                attempt=0,
                created_at=now,
                cancellation_requested=False,
            ),
        ]
    )
    audit(session, "submit", experiment.id)
    session.flush()
    return save(session, key, fingerprint, resource(session, experiment, metadata), 202)


@router.get("/experiments", response_model=ExperimentPage, tags=["admin"])
def list_experiments(
    identity: Admin, session: DB, limit: Limit = 20, cursor: Cursor = None
) -> ExperimentPage:
    query = (
        sa.select(Experiment, ExperimentMetadata)
        .outerjoin(ExperimentMetadata, ExperimentMetadata.experiment_id == Experiment.id)
        .where(ExperimentMetadata.archived_at.is_(None))
        .order_by(Experiment.id)
        .limit(limit + 1)
    )
    if cursor is not None:
        query = query.where(Experiment.id > cursor)
    rows = session.execute(query).all()
    return ExperimentPage(
        items=[resource(session, exp, meta) for exp, meta in rows[:limit]],
        next_cursor=rows[limit - 1][0].id if len(rows) > limit else None,
    )


@router.get("/experiments/{identifier}", response_model=ExperimentResource, tags=["admin"])
def get_experiment(identifier: Identifier, identity: Admin, session: DB) -> ExperimentResource:
    return resource(session, *lookup(session, identifier))


def editable(
    session: Session, identifier: str, version: int
) -> tuple[Experiment, ExperimentMetadata]:
    experiment, metadata = lookup(session, identifier)
    if metadata is None:
        metadata = ExperimentMetadata(experiment_id=identifier, name=identifier, version=1)
        session.add(metadata)
    if metadata.version != version:
        raise APIError(409, "version_conflict", "Experiment metadata version has changed.")
    return experiment, metadata


@router.patch("/experiments/{identifier}", response_model=ExperimentResource, tags=["admin"])
def rename_experiment(
    identifier: Identifier,
    body: RenameRequest,
    request: Request,
    identity: Mutation,
    session: DB,
    key: Key,
) -> ExperimentResource:
    fingerprint = request_hash(request, body.model_dump(mode="json"))
    previous = replay(session, key, fingerprint)
    if previous is not None:
        return previous
    experiment, metadata = editable(session, identifier, body.expected_version)
    metadata.name = body.name
    metadata.version += 1
    audit(session, "update", identifier)
    return save(session, key, fingerprint, resource(session, experiment, metadata), 200)


@router.delete("/experiments/{identifier}", response_model=ExperimentResource, tags=["admin"])
def archive_experiment(
    identifier: Identifier,
    body: VersionRequest,
    request: Request,
    identity: Mutation,
    session: DB,
    now: Clock,
    key: Key,
) -> ExperimentResource:
    fingerprint = request_hash(request, body.model_dump(mode="json"))
    previous = replay(session, key, fingerprint)
    if previous is not None:
        return previous
    experiment, metadata = editable(session, identifier, body.expected_version)
    job = latest_job(session, identifier)
    if job.phase in {"leased", "running"}:
        raise APIError(
            409, "job_active", "Cancel the active job and wait for worker acknowledgement."
        )
    if job.phase == "queued":
        cancel_queued(job, now)
    metadata.archived_at = now
    metadata.version += 1
    audit(session, "delete", identifier)
    return save(session, key, fingerprint, resource(session, experiment, metadata), 200)


def cancel_queued(job: Job, now: datetime) -> None:
    check_transition(cast(JobPhase, job.phase), "cancelled")
    job.phase = "cancelled"
    job.finished_at = max(now, job.created_at)
    job.error_code = "cancelled"
    job.cancellation_requested = True


@router.post("/experiments/{identifier}/cancel", response_model=ExperimentResource, tags=["admin"])
def cancel_experiment(
    identifier: Identifier,
    request: Request,
    identity: Mutation,
    session: DB,
    now: Clock,
    key: Key,
    body: EmptyRequest | None = None,
) -> ExperimentResource:
    fingerprint = request_hash(request, None)
    previous = replay(session, key, fingerprint)
    if previous is not None:
        return previous
    experiment, metadata = lookup(session, identifier)
    job = latest_job(session, identifier)
    if job.phase == "queued":
        cancel_queued(job, now)
    elif job.phase in {"leased", "running"}:
        job.cancellation_requested = True
    elif job.phase != "cancelled":
        raise APIError(409, "invalid_transition", "A terminal job cannot be cancelled.")
    audit(session, "cancel", identifier)
    return save(session, key, fingerprint, resource(session, experiment, metadata), 200)


@router.post(
    "/experiments/{identifier}/retry",
    response_model=ExperimentResource,
    status_code=202,
    tags=["admin"],
)
def retry_experiment(
    identifier: Identifier,
    request: Request,
    identity: Mutation,
    session: DB,
    now: Clock,
    key: Key,
    runner: Runner,
    body: EmptyRequest | None = None,
) -> ExperimentResource:
    fingerprint = request_hash(request, None)
    previous = replay(session, key, fingerprint)
    if previous is not None:
        return previous
    experiment, metadata = lookup(session, identifier)
    job = latest_job(session, identifier)
    if job.phase not in {"failed", "cancelled"}:
        raise APIError(409, "invalid_transition", "Only failed or cancelled jobs may be retried.")
    ensure_capacity(session, now)
    config = to_config(experiment)
    try:
        validate_submission(
            ExperimentSubmitRequest(
                name=metadata.name if metadata else identifier, idempotency_key=key, config=config
            ),
            runner.registry(),
        )
        provenance = runner.resolve(config)
        _validate_provenance(config, provenance)
        if (
            provenance.workload.sha256 != experiment.workload_sha256
            or provenance.hardware.device_name != experiment.device_name
            or provenance.hardware.driver_version != experiment.driver_version
            or provenance.methodology_version != experiment.methodology_version
        ):
            raise ValueError("Pinned provenance changed; submit a new experiment")
    except ValueError:
        raise APIError(
            422, "unapproved_config", "Retry configuration is no longer approved."
        ) from None
    session.add(
        Job(
            id="JOB-" + secrets.token_hex(16),
            experiment_id=identifier,
            idempotency_key=key,
            request_sha256=fingerprint,
            phase="queued",
            attempt=0,
            created_at=max(now, job.created_at + timedelta(microseconds=1)),
            cancellation_requested=False,
        )
    )
    audit(session, "retry", identifier)
    session.flush()
    return save(session, key, fingerprint, resource(session, experiment, metadata), 202)


def report_rows(session: Session, limit: int, cursor: str | None) -> list[PublishedReport]:
    query = sa.select(PublishedReport).order_by(PublishedReport.id).limit(limit + 1)
    if cursor is not None:
        query = query.where(PublishedReport.id > cursor)
    return list(session.scalars(query))


@router.get("/public/reports", response_model=ReportPage, tags=["public"])
def public_reports(session: DB, limit: Limit = 20, cursor: Cursor = None) -> ReportPage:
    rows = report_rows(session, limit, cursor)
    return ReportPage(
        items=[ReportContract.model_validate(row.payload) for row in rows[:limit]],
        next_cursor=rows[limit - 1].id if len(rows) > limit else None,
    )


@router.get("/public/reports/{identifier}", response_model=ReportContract, tags=["public"])
def public_report(identifier: Identifier, session: DB) -> ReportContract:
    row = session.get(PublishedReport, identifier)
    if row is None:
        raise APIError(404, "not_found", "Published report not found.")
    return ReportContract.model_validate(row.payload)


@router.get("/public/metadata", response_model=MetadataPage, tags=["public"])
def public_metadata(session: DB, limit: Limit = 20, cursor: Cursor = None) -> MetadataPage:
    rows = report_rows(session, limit, cursor)
    items = []
    for row in rows[:limit]:
        report = ReportContract.model_validate(row.payload)
        items.append(
            PublicMetadata(
                report_id=report.id,
                engine=report.provenance.engine,
                model=report.provenance.model,
                methodology_version=report.provenance.methodology_version,
            )
        )
    return MetadataPage(items=items, next_cursor=rows[limit - 1].id if len(rows) > limit else None)
