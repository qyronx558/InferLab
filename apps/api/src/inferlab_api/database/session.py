"""Explicit engine/session factories. No .env loading, connections or DDL on import."""

import os
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL, Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "sqlite:///./.local/inferlab.db"


def database_url(value: str | URL | None = None) -> URL:
    url = make_url(
        value
        or os.environ.get("INFERLAB_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or DEFAULT_DATABASE_URL
    )
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername not in {"sqlite", "sqlite+pysqlite", "postgresql+psycopg"}:
        raise ValueError("Only SQLite and PostgreSQL/psycopg database URLs are supported")
    return url


def create_database_engine(value: str | URL | None = None) -> Engine:
    url = database_url(value)
    if url.get_backend_name() == "sqlite":
        if url.database is not None and url.database not in {"", ":memory:"}:
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url, hide_parameters=True, connect_args={"autocommit": False, "timeout": 5}
        )

        @event.listens_for(engine, "connect")
        def sqlite_settings(connection: object, record: object) -> None:
            assert isinstance(connection, sqlite3.Connection)
            previous = connection.autocommit
            connection.autocommit = True
            try:
                connection.execute("PRAGMA foreign_keys=ON")
                connection.execute("PRAGMA busy_timeout=5000")
            finally:
                connection.autocommit = previous

        return engine
    return create_engine(url, hide_parameters=True, pool_pre_ping=True)


def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
