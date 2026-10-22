"""Shared transaction serialization and database-authoritative lease timestamps."""

from datetime import UTC, datetime
from typing import cast

import sqlalchemy as sa
from sqlalchemy.orm import Session

from .models import APIControl


def lock_admission(session: Session) -> APIControl:
    changed = session.connection().execute(
        sa.update(APIControl).where(APIControl.id == 1).values(revision=APIControl.revision + 1)
    )
    if changed.rowcount != 1:
        raise RuntimeError("Apply database migrations first")
    return session.scalars(sa.select(APIControl).execution_options(populate_existing=True)).one()


def database_now(session: Session) -> datetime:
    if session.get_bind().dialect.name == "sqlite":
        value = cast(
            str, session.scalar(sa.select(sa.func.strftime("%Y-%m-%dT%H:%M:%f+00:00", "now")))
        )
        return datetime.fromisoformat(value)
    # PostgreSQL CURRENT_TIMESTAMP is fixed at transaction start; a lock wait must
    # not make a lease renewal use an old timestamp.
    return cast(datetime, session.scalar(sa.select(sa.func.clock_timestamp()))).astimezone(UTC)
