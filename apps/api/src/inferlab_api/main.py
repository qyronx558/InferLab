"""Local API factory: no migrations, model loading or execution at import/startup."""

import os
import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import JSONResponse

from .database.models import utc_now
from .database.session import create_database_engine, session_factory
from .dependencies import RunnerPort, Settings
from .errors import APIError
from .http_contracts import ErrorResponse
from .middleware import RequestBoundary
from .resources import router as resources
from .security import COOKIE, audit
from .security import router as authentication


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    execution: Literal["not_configured"] = "not_configured"


def create_app(
    *,
    engine: Engine | None = None,
    settings: Settings | None = None,
    runner: RunnerPort | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        owned = None
        if engine is None and (os.getenv("INFERLAB_DATABASE_URL") or os.getenv("DATABASE_URL")):
            owned = create_database_engine()
            application.state.session_factory = session_factory(owned)
        try:
            yield
        finally:
            if owned is not None:
                owned.dispose()
                application.state.session_factory = None

    config = settings or Settings.from_environment()
    application = FastAPI(
        title="InferLab local API",
        version="0.2.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
        responses={
            status: {"model": ErrorResponse}
            for status in (400, 401, 403, 404, 405, 409, 413, 415, 422, 429, 500, 503)
        },
    )
    application.state.settings = config
    application.state.session_factory = session_factory(engine) if engine is not None else None
    application.state.runner = runner
    application.state.clock = clock
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[config.origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token", "Idempotency-Key"],
        expose_headers=["X-Request-ID"],
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])
    application.add_middleware(RequestBoundary)

    def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status,
            headers={
                "X-Request-ID": getattr(request.state, "request_id", "unavailable"),
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
            content={
                "error": {
                    "code": code,
                    "message": message,
                    "request_id": getattr(request.state, "request_id", "unavailable"),
                }
            },
        )

    def record_failure(request: Request, code: str) -> None:
        factory = cast(sessionmaker[Session] | None, application.state.session_factory)
        if (
            factory is not None
            and request.method in {"POST", "PATCH", "DELETE"}
            and request.cookies.get(COOKIE)
            and not request.url.path.startswith("/api/v1/auth/login")
        ):
            action = {"PATCH": "update", "DELETE": "delete"}.get(request.method, "submit")
            for suffix, value in (
                ("/cancel", "cancel"),
                ("/retry", "retry"),
                ("/logout", "logout"),
            ):
                if request.url.path.endswith(suffix):
                    action = value
            subject = str(request.path_params.get("identifier", "admin"))
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", subject) is None:
                subject = "admin"
            try:
                with factory() as session:
                    session.info["request_id"] = request.state.request_id
                    audit(
                        session,
                        action,
                        subject,
                        failure=code,
                        actor="admin"
                        if getattr(request.state, "admin_authenticated", False)
                        else "system",
                    )
                    session.commit()
            except SQLAlchemyError:
                pass

    @application.exception_handler(APIError)
    async def api_error(request: Request, error: APIError) -> JSONResponse:
        record_failure(
            request, "unauthorized" if error.status in {401, 403} else "validation_error"
        )
        return error_response(request, error.status, error.code, error.message)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        record_failure(request, "validation_error")
        return error_response(request, 422, "validation_error", "Request failed schema validation.")

    @application.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        return error_response(request, error.status_code, "http_error", "HTTP request rejected.")

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request: Request, error: SQLAlchemyError) -> JSONResponse:
        if isinstance(error, IntegrityError):
            return error_response(
                request, 409, "storage_conflict", "Request conflicts with stored evidence."
            )
        return error_response(
            request, 503, "storage_unavailable", "Storage is unavailable; retry with the same key."
        )

    @application.exception_handler(Exception)
    async def internal_error(request: Request, error: Exception) -> JSONResponse:
        return error_response(request, 500, "internal_error", "Unexpected server error.")

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    application.include_router(authentication)
    application.include_router(resources)
    return application


app = create_app()
