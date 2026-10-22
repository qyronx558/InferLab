"""Explicit operator wiring. Importing this module opens no database or engine."""

import os
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, cast
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from .contracts import ExperimentConfig, Provenance, Registry
from .errors import APIError


class RunnerPort(Protocol):
    """Admission only; implementations must not start inference in an HTTP request.

    Resolve a bounded config against an operator-approved local registry/hardware
    snapshot, including while the worker is offline. Execution belongs to a worker
    polling committed jobs; no default runner or synthetic provenance is installed.
    """

    def registry(self) -> Registry: ...

    def resolve(self, config: ExperimentConfig) -> Provenance: ...


class UnconfiguredRunner:
    def registry(self) -> Registry:
        raise APIError(
            503, "runner_not_configured", "Operator admission provider is not configured."
        )

    def resolve(self, config: ExperimentConfig) -> Provenance:
        raise APIError(
            503, "runner_not_configured", "Operator admission provider is not configured."
        )


@dataclass(frozen=True)
class Settings:
    origin: str = "https://127.0.0.1:5173"
    password_hash: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        origin = urlsplit(self.origin)
        if (
            origin.scheme != "https"
            or origin.hostname not in {"127.0.0.1", "localhost"}
            or origin.path
            or origin.query
            or origin.fragment
            or origin.username
            or origin.password
        ):
            raise ValueError("Console origin must be an exact HTTPS loopback origin")
        _ = origin.port  # Reject malformed port syntax during operator setup.

    @classmethod
    def from_environment(cls) -> "Settings":
        return cls(
            origin=os.getenv("INFERLAB_CONSOLE_ORIGIN", "https://127.0.0.1:5173"),
            password_hash=os.getenv("INFERLAB_ADMIN_PASSWORD_HASH"),
        )


def get_settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def get_session(request: Request) -> Iterator[Session]:
    factory = cast(sessionmaker[Session] | None, request.app.state.session_factory)
    if factory is None:
        raise APIError(503, "database_not_configured", "Configure a migrated local database.")
    with factory() as session:
        session.info["request_id"] = request.state.request_id
        try:
            yield session
        finally:
            session.rollback()


def get_runner(request: Request) -> RunnerPort:
    runner = cast(RunnerPort | None, request.app.state.runner)
    return runner if runner is not None else UnconfiguredRunner()


def get_now(request: Request) -> datetime:
    return cast(datetime, request.app.state.clock())
