"""Explicit Alembic entry point; imports metadata, never runs benchmark services."""

from typing import Literal

from alembic import context
from alembic.autogenerate.api import AutogenContext
from sqlalchemy.engine import Connection

from inferlab_api.database.models import Base
from inferlab_api.database.session import create_database_engine, database_url
from inferlab_api.database.types import (
    SHA256,
    FiniteMeasurement,
    Identifier,
    ReportSnapshot,
    UTCDateTime,
)

config = context.config
target_metadata = Base.metadata


def render_item(kind: str, value: object, autogen_context: AutogenContext) -> str | Literal[False]:
    """Freeze portable SQL types in revisions instead of importing live model classes."""
    if kind == "type":
        if isinstance(value, UTCDateTime):
            return "sa.DateTime(timezone=True)"
        if isinstance(value, (Identifier, SHA256)):
            return "sa.String(length=64)"
        if isinstance(value, FiniteMeasurement):
            return "sa.Float()"
        if isinstance(value, ReportSnapshot):
            return "sa.JSON()"
    return False


def run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.dialect.name == "sqlite",
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(
        url=database_url(config.attributes.get("database_url")),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    supplied = config.attributes.get("connection")
    if supplied is not None:
        if not isinstance(supplied, Connection):
            raise TypeError("Alembic connection attribute must be a SQLAlchemy Connection")
        run(supplied)
    else:
        engine = create_database_engine(config.attributes.get("database_url"))
        try:
            with engine.connect() as connection:
                run(connection)
        finally:
            engine.dispose()
