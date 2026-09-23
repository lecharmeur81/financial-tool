"""Shared request-parameter helpers."""

from __future__ import annotations

from datetime import datetime

from cfi.core.errors import DataValidationError
from cfi.core.time import ensure_utc


def aware(value: datetime | None, name: str) -> datetime | None:
    """A timezone-aware query timestamp in UTC; naive values are rejected, never assumed."""
    if value is None:
        return None
    try:
        return ensure_utc(value, field=name)
    except ValueError as exc:
        raise DataValidationError(f"'{name}' must include a time zone offset (e.g. Z).") from exc
