"""Single-admin server-side sessions, exact origins, CSRF and durable limits."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta
from typing import Annotated

import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import APIRouter, Depends, Request, Response, Security
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from .database.coordination import lock_admission
from .database.models import AdminSession, APIControl, AuditEvent
from .dependencies import Settings, get_now, get_session, get_settings
from .errors import APIError
from .http_contracts import LoginRequest, SessionInfo

COOKIE = "__Host-inferlab_session"
SESSION_HOURS = 12
COOKIE_MAX_AGE_SECONDS = SESSION_HOURS * 3600
cookie_scheme = APIKeyCookie(name=COOKIE, auto_error=False)
router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
DB = Annotated[Session, Depends(get_session)]
Clock = Annotated[datetime, Depends(get_now)]
Config = Annotated[Settings, Depends(get_settings)]


def session_key(token: str, password_hash: str) -> str:
    """Key server-side sessions to the provisioned credential.

    Only this HMAC digest is stored. Changing the configured password hash changes
    the key, so every existing session fails closed without manual DB surgery.
    """
    return hmac.new(password_hash.encode(), token.encode(), hashlib.sha256).hexdigest()


def audit(
    session: Session,
    action: str,
    subject: str,
    *,
    failure: str | None = None,
    actor: str = "admin",
) -> None:
    session.add(
        AuditEvent(
            id="AUD-" + session.info.get("request_id", secrets.token_hex(16)),
            actor=actor,
            action=action,
            outcome="failure" if failure else "success",
            subject_type="system" if subject == "admin" else "experiment",
            subject_id=subject,
            reason_code=failure,
        )
    )


def lock_control(session: Session) -> APIControl:
    # UPDATE first acquires a SQLite write reservation or a PostgreSQL row lock.
    # Every API write uses this same row before admission checks or evidence reads.
    try:
        return lock_admission(session)
    except RuntimeError:
        raise APIError(503, "database_not_ready", "Apply database migrations first.") from None


def check_origin(request: Request, settings: Settings) -> None:
    if request.url.scheme != "https":
        raise APIError(403, "https_required", "Admin authentication requires local HTTPS.")
    if request.headers.get("origin") != settings.origin:
        raise APIError(403, "invalid_origin", "Console origin is not allowed.")


def require_cookie(request: Request, token: Annotated[str | None, Security(cookie_scheme)]) -> str:
    if token is None or len(token) != 64 or any(c not in "0123456789abcdef" for c in token):
        raise APIError(401, "unauthorized", "An authenticated admin session is required.")
    if request.url.scheme != "https":
        raise APIError(403, "https_required", "Admin authentication requires local HTTPS.")
    return token


def require_admin(
    request: Request,
    token: Annotated[str, Depends(require_cookie)],
    session: DB,
    settings: Config,
    now: Clock,
) -> AdminSession:
    if not settings.password_hash:
        raise APIError(503, "auth_not_configured", "Provision the local admin password hash.")
    identity = session.get(AdminSession, session_key(token, settings.password_hash))
    if identity is None or identity.expires_at <= now:
        raise APIError(401, "unauthorized", "An authenticated admin session is required.")
    request.state.admin_authenticated = True
    return identity


Admin = Annotated[AdminSession, Depends(require_admin)]


def require_mutation(
    request: Request, identity: Admin, session: DB, settings: Config, now: Clock
) -> AdminSession:
    check_origin(request, settings)
    token = request.headers.get("x-csrf-token", "")
    if not hmac.compare_digest(token.encode(), identity.csrf_token.encode()):
        raise APIError(403, "invalid_csrf", "A valid CSRF token is required.")
    control = lock_control(session)
    # Recheck under the write lock: logout/expiry may race authentication.
    current = session.get(AdminSession, identity.token_sha256, populate_existing=True)
    if current is None or current.expires_at <= now:
        raise APIError(401, "unauthorized", "Admin session expired.")
    if now >= control.mutation_window + timedelta(minutes=1):
        control.mutation_window = now
        control.mutation_count = 0
    if control.mutation_count >= 20:
        raise APIError(429, "mutation_limit", "Admin mutation limit reached; retry later.")
    control.mutation_count += 1
    # Persist the rate charge even if later validation/admission rolls back.
    session.commit()
    lock_control(session)
    current = session.get(AdminSession, identity.token_sha256, populate_existing=True)
    if current is None or current.expires_at <= now:
        raise APIError(401, "unauthorized", "Admin session expired or revoked.")
    return identity


Mutation = Annotated[AdminSession, Depends(require_mutation)]


@router.post("/login", response_model=SessionInfo)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: DB,
    settings: Config,
    now: Clock,
) -> SessionInfo:
    check_origin(request, settings)
    password_hash = settings.password_hash
    if not password_hash or not password_hash.startswith("$argon2id$"):
        raise APIError(503, "auth_not_configured", "Provision the local admin password hash.")
    control = lock_control(session)
    if control.locked_until is not None and now < control.locked_until:
        raise APIError(429, "login_locked", "Admin login is temporarily locked.")
    if now >= control.login_window + timedelta(minutes=15):
        control.login_window = now
        control.failed_logins = 0
    try:
        PasswordHasher().verify(password_hash, body.password.get_secret_value())
    except InvalidHashError:
        raise APIError(
            503, "auth_not_configured", "Provision a valid Argon2id password hash."
        ) from None
    except VerificationError:
        control.failed_logins += 1
        if control.failed_logins >= 5:
            control.locked_until = now + timedelta(minutes=15)
        audit(session, "login", "admin", failure="invalid_credentials")
        session.commit()
        raise APIError(401, "invalid_credentials", "Invalid admin credentials.") from None
    control.failed_logins = 0
    control.locked_until = None
    # One admin and one active session. A fresh login revokes older sessions.
    session.execute(sa.delete(AdminSession))
    raw_token = secrets.token_hex(32)
    identity = AdminSession(
        token_sha256=session_key(raw_token, password_hash),
        csrf_token=secrets.token_hex(32),
        expires_at=now + timedelta(hours=SESSION_HOURS),
    )
    session.add(identity)
    audit(session, "login", "admin")
    session.commit()
    response.set_cookie(
        COOKIE,
        raw_token,
        max_age=COOKIE_MAX_AGE_SECONDS,
        secure=True,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return SessionInfo(csrf_token=identity.csrf_token, expires_at=identity.expires_at)


@router.get("/session", response_model=SessionInfo)
def current_session(identity: Admin) -> SessionInfo:
    return SessionInfo(csrf_token=identity.csrf_token, expires_at=identity.expires_at)


@router.post("/logout", status_code=204)
def logout(response: Response, identity: Mutation, session: DB) -> None:
    session.delete(identity)
    audit(session, "logout", "admin")
    session.commit()
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="strict", path="/")
