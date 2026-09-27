"""Unit tests for cfi.regime.snapshot's plain extraction helpers (``_score_reading``, ``_decimal``)
— the pure parsing logic that turns each domain service's already-serialized (string-encoded)
payload back into a ``MetricReading``. The async ``gather_snapshot`` orchestration itself is
exercised against a real database in ``tests/integration/test_regime_api.py``."""

from __future__ import annotations

from decimal import Decimal

from cfi.regime.snapshot import _decimal, _score_reading


def test_decimal_parses_numeric_strings_and_passes_through_none() -> None:
    assert _decimal("12.5") == Decimal("12.5")
    assert _decimal(None) is None
    assert _decimal("not-a-number") is None


def test_score_reading_ok_status_extracts_the_named_value() -> None:
    reading = _score_reading({"status": "ok", "score": "42.5"}, value_key="score")
    assert reading.status == "ok"
    assert reading.value == Decimal("42.5")


def test_score_reading_non_ok_status_is_unavailable_or_insufficient() -> None:
    assert _score_reading({"status": "unavailable"}).status == "unavailable"
    assert _score_reading({"status": "insufficient_data"}).status == "insufficient_data"
    assert _score_reading({}).status == "unavailable"


def test_score_reading_default_value_key_is_value() -> None:
    reading = _score_reading({"status": "ok", "value": "7"})
    assert reading.value == Decimal(7)
