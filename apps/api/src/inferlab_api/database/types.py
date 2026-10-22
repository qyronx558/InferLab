"""Portable persisted values with explicit UTC, identifier and finite-number rules."""

import math
import re
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from inferlab_api.contracts import PublishedReport as ReportContract


class Identifier(TypeDecorator[str]):
    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value
        ):
            raise ValueError("Invalid stored identifier")
        return value


class SHA256(TypeDecorator[str]):
    impl = String(64)
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("Invalid SHA-256")
        return value


class UTCDateTime(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError("Stored timestamps must be timezone-aware")
        utc = value.astimezone(UTC)
        return utc.replace(tzinfo=None) if dialect.name == "sqlite" else utc

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class FiniteMeasurement(TypeDecorator[float]):
    impl = Float
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("Measurement must be a genuine number")
        result = float(value)
        if not math.isfinite(result) or result < 0:
            raise ValueError("Measurement must be finite and nonnegative")
        return result


class ReportSnapshot(TypeDecorator[dict[str, Any]]):
    """Allowlisted, bounded publication evidence; never a general JSON/log blob."""

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: object, dialect: Dialect) -> dict[str, Any] | None:
        if value is None:
            return None
        report = ReportContract.model_validate(value)
        if len(report.model_dump_json().encode("utf-8")) > 262_144:
            raise ValueError("Report snapshot exceeds 256 KiB")
        return report.model_dump(mode="json")
