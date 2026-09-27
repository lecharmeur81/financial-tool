"""New Phase 12 endpoint on an already-integrated provider: CoinGecko's ``/global`` (TOTAL market
capitalisation, no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.core.errors import DataValidationError, SchemaMismatchError
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.market_structure.universe import GLOBAL_SUBJECT, TOTAL_MARKET_CAP_USD
from cfi.providers.base import FetchWindow, NormaliseContext, RawResponse
from cfi.providers.coingecko import GLOBAL_PATH, CoinGecko

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
WINDOW = FetchWindow(NOW - timedelta(days=1), NOW, GLOBAL_SUBJECT)


def raw(provider: str, path: str, body: object) -> RawResponse:
    return RawResponse(provider, path, {}, NOW, 200, "application/json", json.dumps(body).encode())


def ctx(at: datetime = NOW) -> NormaliseContext:
    return NormaliseContext(dataset=TOTAL_MARKET_CAP_USD, ingested_at=at, raw_ref=1)


def test_first_request_total_market_cap_needs_no_params() -> None:
    adapter = CoinGecko()
    spec = adapter.first_request(TOTAL_MARKET_CAP_USD.dataset_id, WINDOW)
    assert spec.path == GLOBAL_PATH
    assert spec.params == {}


def test_parse_total_market_cap_reads_data_block() -> None:
    adapter = CoinGecko()
    body = {
        "data": {
            "total_market_cap": {"usd": 2_500_000_000_000.5},
            "market_cap_percentage": {"btc": 55.1, "eth": 12.3},
            "updated_at": 1_758_888_000,
        }
    }
    (record,) = adapter.parse(raw("coingecko", GLOBAL_PATH, body))
    assert record.dataset_id == TOTAL_MARKET_CAP_USD.dataset_id
    assert record.payload["total_market_cap_usd"] == 2_500_000_000_000.5
    assert record.payload["updated_at"] == 1_758_888_000
    # CoinGecko's own dominance percentage is never carried into the payload (see universe.py /
    # providers/coingecko.py docstrings: dominance is calculated, not ingested).
    assert "market_cap_percentage" not in record.payload


def test_parse_total_market_cap_rejects_response_without_data_block() -> None:
    adapter = CoinGecko()
    with pytest.raises(SchemaMismatchError):
        adapter.parse(raw("coingecko", GLOBAL_PATH, {"nope": True}))


def test_parse_total_market_cap_rejects_missing_total_market_cap_usd() -> None:
    adapter = CoinGecko()
    body = {"data": {"total_market_cap": {"eur": 1}, "updated_at": 1_758_888_000}}
    with pytest.raises(SchemaMismatchError):
        adapter.parse(raw("coingecko", GLOBAL_PATH, body))


def test_parse_total_market_cap_rejects_missing_updated_at() -> None:
    adapter = CoinGecko()
    body = {"data": {"total_market_cap": {"usd": 1}}}
    with pytest.raises(SchemaMismatchError):
        adapter.parse(raw("coingecko", GLOBAL_PATH, body))


def test_normalise_total_market_cap_builds_canonical_observation() -> None:
    adapter = CoinGecko()
    body = {"data": {"total_market_cap": {"usd": 2_000_000_000_000}, "updated_at": 1_758_888_000}}
    (record,) = adapter.parse(raw("coingecko", GLOBAL_PATH, body))
    obs = adapter.normalise(record, ctx())
    assert isinstance(obs, CanonicalObservation)
    assert obs.asset == GLOBAL_SUBJECT
    assert obs.subject_ref == GLOBAL_SUBJECT
    assert obs.value == Decimal(2_000_000_000_000)
    assert obs.event_time == datetime(2025, 9, 26, 12, tzinfo=UTC)
    assert obs.quality_status is QualityStatus.OK


def test_normalise_total_market_cap_rejects_non_positive_value() -> None:
    adapter = CoinGecko()
    body = {"data": {"total_market_cap": {"usd": 0}, "updated_at": 1_758_888_000}}
    (record,) = adapter.parse(raw("coingecko", GLOBAL_PATH, body))
    with pytest.raises(DataValidationError):
        adapter.normalise(record, ctx())


def test_normalise_total_market_cap_rejects_non_integer_updated_at() -> None:
    adapter = CoinGecko()
    body = {"data": {"total_market_cap": {"usd": 1_000}, "updated_at": "not-an-epoch"}}
    (record,) = adapter.parse(raw("coingecko", GLOBAL_PATH, body))
    with pytest.raises(DataValidationError):
        adapter.normalise(record, ctx())


def test_capabilities_include_total_market_cap_dataset() -> None:
    adapter = CoinGecko()
    assert TOTAL_MARKET_CAP_USD.dataset_id in adapter.capabilities.datasets
