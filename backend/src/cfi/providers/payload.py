"""Helpers shared by real adapters for reading provider payloads safely."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.core.errors import DataValidationError, SchemaMismatchError
from cfi.providers.base import RawResponse


def load_json(raw: RawResponse) -> Any:
    """Parse a JSON body. Numbers with a fraction become ``Decimal`` (never binary floats), so a
    price is stored exactly as the provider wrote it."""
    try:
        return json.loads(raw.body, parse_float=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SchemaMismatchError(
            f"Malformed response from '{raw.provider_id}': body is not valid JSON.",
            provider_id=raw.provider_id,
        ) from exc


def schema_error(raw: RawResponse, what: str) -> SchemaMismatchError:
    return SchemaMismatchError(
        f"Response from '{raw.provider_id}' ({raw.endpoint}) does not match the expected schema: "
        f"{what}.",
        provider_id=raw.provider_id,
    )


def to_decimal(value: object, field: str) -> Decimal:
    """Exact decimal from a JSON number or numeric string; anything else is rejected."""
    if isinstance(value, bool) or value is None:
        raise DataValidationError(f"{field} is not a number: {value!r}")
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise DataValidationError(f"{field} is not a number: {value!r}") from exc
    if not number.is_finite():
        raise DataValidationError(f"{field} is not a finite number: {value!r}")
    return number
