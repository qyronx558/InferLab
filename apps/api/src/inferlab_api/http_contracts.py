"""HTTP resource contracts, separate from the existing dashboard demo catalog."""

from datetime import datetime
from typing import Annotated

from pydantic import Field, SecretStr

from .contracts import (
    Contract,
    Engine,
    ExperimentConfig,
    Identifier,
    Job,
    Model,
    PublishedReport,
    ShortText,
)


class LoginRequest(Contract):
    password: SecretStr = Field(min_length=1, max_length=1024)


class SessionInfo(Contract):
    identity: str = "admin"
    csrf_token: str
    expires_at: datetime


class RenameRequest(Contract):
    name: ShortText
    expected_version: Annotated[int, Field(strict=True, ge=1)]


class VersionRequest(Contract):
    expected_version: Annotated[int, Field(strict=True, ge=1)]


class EmptyRequest(Contract):
    pass


class ExperimentResource(Contract):
    id: Identifier
    name: ShortText
    version: Annotated[int, Field(strict=True, ge=1)]
    archived_at: datetime | None
    config: ExperimentConfig
    job: Job


class ExperimentPage(Contract):
    items: list[ExperimentResource]
    next_cursor: Identifier | None


class ReportPage(Contract):
    items: list[PublishedReport]
    next_cursor: Identifier | None


class PublicMetadata(Contract):
    report_id: Identifier
    engine: Engine
    model: Model
    methodology_version: Identifier


class MetadataPage(Contract):
    items: list[PublicMetadata]
    next_cursor: Identifier | None


class ErrorDetail(Contract):
    code: str
    message: str
    request_id: str


class ErrorResponse(Contract):
    error: ErrorDetail
