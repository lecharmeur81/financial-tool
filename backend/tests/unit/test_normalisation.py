"""Timestamp/timezone normalisation, availability rules, adapter normalisation and validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.core.errors import DataValidationError, SchemaMismatchError
from cfi.core.time import floor_to_period, from_epoch, parse_period, parse_timestamp
from cfi.domain.datasets import AvailabilityRule, DatasetSpec
from cfi.domain.enums import QualityStatus
from cfi.providers.base import NormaliseContext, ProviderRecord, RawResponse
from cfi.providers.mock import MOCK_DATASET, MockProviderA, MockProviderB
from tests.support import T0

INGESTED = T0 + timedelta(days=1)
CTX = NormaliseContext(dataset=MOCK_DATASET, ingested_at=INGESTED, raw_ref=42)


# ------------------------------------------------------------------ timestamps


def test_epoch_units_are_explicit() -> None:
    assert from_epoch(1_756_684_800_000, "ms") == datetime(2025, 9, 1, tzinfo=UTC)
    assert from_epoch("1756684800", "s") == datetime(2025, 9, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="epoch"):
        from_epoch("abc", "s")


def test_iso_with_offset_converts_to_utc() -> None:
    assert parse_timestamp("2026-09-01T08:00:00+08:00") == T0
    assert parse_timestamp("2026-09-01T00:00:00Z") == T0


@pytest.mark.parametrize(
    ("local", "utc_hour"),
    [
        ("2026-01-15 09:00:00", 14),  # EST, UTC-5
        ("2026-07-15 09:00:00", 13),  # EDT, UTC-4 (daylight saving)
    ],
)
def test_naive_time_uses_declared_zone_with_dst(local: str, utc_hour: int) -> None:
    assert parse_timestamp(local, source_timezone="America/New_York").hour == utc_hour


def test_naive_time_without_zone_is_rejected() -> None:
    with pytest.raises(ValueError, match="no offset"):
        parse_timestamp("2026-09-01 08:00:00")
    with pytest.raises(ValueError, match="unknown time zone"):
        parse_timestamp("2026-09-01 08:00:00", source_timezone="Mars/Olympus")


def test_periods() -> None:
    assert parse_period("1h") == timedelta(hours=1)
    assert parse_period("event") is None
    with pytest.raises(ValueError, match="unsupported"):
        parse_period("1y")
    assert floor_to_period(T0 + timedelta(minutes=59), timedelta(hours=1)) == T0


# ------------------------------------------------------------------ availability (point in time)


def test_bar_is_available_after_close_plus_delay() -> None:
    available, estimated = MOCK_DATASET.available_at(T0, None, INGESTED)
    assert available == T0 + timedelta(hours=1, minutes=1)
    assert estimated is True


def test_unfinished_bar_is_rejected() -> None:
    with pytest.raises(DataValidationError, match="not final"):
        MOCK_DATASET.available_at(T0, None, T0 + timedelta(minutes=30))


def test_provider_publication_time_is_used_when_given() -> None:
    spec = DatasetSpec(
        dataset_id="x",
        metric="m",
        unit="usd",
        period="1d",
        availability=AvailabilityRule("provider"),
        freshness_limit=timedelta(days=2),
        conflict_tolerance=Decimal(0),
    )
    published = T0 + timedelta(hours=14)
    assert spec.available_at(T0, published, INGESTED) == (published, False)
    assert spec.available_at(T0, None, INGESTED) == (INGESTED, True)  # conservative fallback


# ------------------------------------------------------------------ adapters


def _raw(provider: str, body: bytes) -> RawResponse:
    return RawResponse(provider, "/x", {}, INGESTED, 200, "application/json", body)


def test_provider_a_normalisation_and_provenance() -> None:
    adapter = MockProviderA()
    record = ProviderRecord(
        "mock_a", MOCK_DATASET.dataset_id, {"t": 1788220800000, "symbol": "BTCUSD", "close": "1.5"}
    )
    obs = adapter.normalise(record, CTX)
    # what / when / ingested / where / who / unit / asset / reliability / transformed
    assert obs.metric == "close_price"
    assert obs.event_time == datetime(2026, 9, 1, tzinfo=UTC)
    assert obs.ingested_at == INGESTED
    assert (obs.original_source, obs.raw_ref) == ("mock_exchange_a", 42)
    assert obs.source_provider == "mock_a"
    assert obs.unit == "usd"
    assert obs.asset == "BTC"
    assert obs.quality_status is QualityStatus.OK
    assert obs.transformed
    assert "epoch milliseconds" in obs.transformations[0]
    assert obs.value == Decimal("1.5")


def test_provider_b_converts_cents_and_local_time() -> None:
    adapter = MockProviderB()
    record = ProviderRecord(
        "mock_b",
        MOCK_DATASET.dataset_id,
        {"time": "2026-08-31 20:00:00", "ticker": "XBT", "close_cents": 6300050},
    )
    obs = adapter.normalise(record, CTX)
    assert obs.event_time == T0  # 20:00 EDT = 00:00 UTC next day
    assert obs.value == Decimal("63000.50")
    assert any("cents" in t for t in obs.transformations)


def test_null_value_becomes_explicit_missing() -> None:
    record = ProviderRecord(
        "mock_a", MOCK_DATASET.dataset_id, {"t": 1788220800000, "symbol": "BTCUSD", "close": None}
    )
    obs = MockProviderA().normalise(record, CTX)
    assert obs.value is None
    assert obs.quality_status is QualityStatus.MISSING
    assert obs.quality_note


def test_unknown_symbol_is_rejected() -> None:
    record = ProviderRecord(
        "mock_a", MOCK_DATASET.dataset_id, {"t": 1788220800000, "symbol": "DOGEUSD", "close": "1"}
    )
    with pytest.raises(DataValidationError, match="unknown symbol"):
        MockProviderA().normalise(record, CTX)


def test_malformed_json_is_a_schema_mismatch() -> None:
    with pytest.raises(SchemaMismatchError, match="not valid JSON"):
        MockProviderA().parse(_raw("mock_a", b"{not json"))


def test_changed_schema_is_detected() -> None:
    body = b'{"data": [{"timestamp": 1, "symbol": "BTCUSD", "close": "1"}]}'
    with pytest.raises(SchemaMismatchError, match=r"data\.0\.t"):
        MockProviderA().parse(_raw("mock_a", body))
