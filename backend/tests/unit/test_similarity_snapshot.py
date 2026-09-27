"""Unit tests for cfi.similarity.snapshot's plain extraction helpers. The async ``gather_snapshot``
orchestration itself is exercised against a real database in
``tests/integration/test_similarity_api.py``."""

from __future__ import annotations

from decimal import Decimal

from cfi.similarity.snapshot import _decimal, _field_reading, _score_reading


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


def test_field_reading_none_value_is_insufficient_data() -> None:
    reading = _field_reading({"annualised_7d_pct": None}, "annualised_7d_pct")
    assert reading.status == "insufficient_data"
    assert reading.value is None


def test_field_reading_present_value_is_ok() -> None:
    reading = _field_reading({"change_7d_pct": "3.25"}, "change_7d_pct")
    assert reading.status == "ok"
    assert reading.value == Decimal("3.25")
