"""New Phase 10 endpoints on two already-integrated providers: CoinGecko's ``/search/trending``
and Blockchair's small-output-count aggregation (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.core.errors import DataValidationError, ProviderNotConfiguredError, SchemaMismatchError
from cfi.domain.datasets import DatasetSpec
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.providers.base import FetchWindow, NormaliseContext, RawResponse
from cfi.providers.blockchair import Blockchair
from cfi.providers.coingecko import CoinGecko
from cfi.retail.universe import SMALL_OUTPUT_COUNT, TRENDING, TRENDING_SUBJECT, coin_ref

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
WINDOW = FetchWindow(NOW - timedelta(days=1), NOW, TRENDING_SUBJECT)


def raw(
    provider: str, path: str, body: object, params: dict[str, str] | None = None
) -> RawResponse:
    return RawResponse(
        provider, path, params or {}, NOW, 200, "application/json", json.dumps(body).encode()
    )


def ctx(dataset: DatasetSpec, at: datetime = NOW) -> NormaliseContext:
    return NormaliseContext(dataset=dataset, ingested_at=at, raw_ref=1)


# --------------------------------------------------------------------------- CoinGecko trending


def test_first_request_trending_needs_no_params() -> None:
    adapter = CoinGecko()
    spec = adapter.first_request(TRENDING.dataset_id, WINDOW)
    assert spec.path == "/search/trending"
    assert spec.params == {}


def test_parse_trending_builds_one_record_per_coin() -> None:
    adapter = CoinGecko()
    body = {
        "coins": [
            {"item": {"id": "dogecoin", "symbol": "doge", "name": "Dogecoin", "score": 0}},
            {"item": {"id": "shiba-inu", "symbol": "shib", "name": "Shiba Inu", "score": 1}},
        ],
        "nfts": [],
        "categories": [],
    }
    records = adapter.parse(raw("coingecko", "/search/trending", body))
    assert [r.payload["symbol"] for r in records] == ["doge", "shib"]
    assert [r.payload["score"] for r in records] == [0, 1]
    assert all(r.dataset_id == TRENDING.dataset_id for r in records)


def test_parse_trending_rejects_response_without_coins_list() -> None:
    adapter = CoinGecko()
    with pytest.raises(SchemaMismatchError, match="'coins' list"):
        adapter.parse(raw("coingecko", "/search/trending", {"nfts": []}))


def test_parse_trending_rejects_item_missing_required_field() -> None:
    adapter = CoinGecko()
    body = {"coins": [{"item": {"id": "dogecoin", "symbol": "doge"}}]}  # no score
    with pytest.raises(SchemaMismatchError, match="score"):
        adapter.parse(raw("coingecko", "/search/trending", body))


def test_normalise_trending_builds_canonical_observation() -> None:
    adapter = CoinGecko()
    body = {"coins": [{"item": {"id": "dogecoin", "symbol": "doge", "score": 3}}]}
    (record,) = adapter.parse(raw("coingecko", "/search/trending", body))
    obs = adapter.normalise(record, ctx(TRENDING))
    assert isinstance(obs, CanonicalObservation)
    assert obs.asset == "DOGE"
    assert obs.subject_ref == coin_ref("dogecoin")
    assert obs.value == Decimal(3)
    assert obs.event_time == NOW  # receipt time — the endpoint has no timestamp of its own
    assert obs.quality_status is QualityStatus.OK


def test_normalise_trending_rejects_negative_score() -> None:
    adapter = CoinGecko()
    body = {"coins": [{"item": {"id": "dogecoin", "symbol": "doge", "score": -1}}]}
    (record,) = adapter.parse(raw("coingecko", "/search/trending", body))
    with pytest.raises(DataValidationError, match="negative"):
        adapter.normalise(record, ctx(TRENDING))


def test_capabilities_include_trending_dataset() -> None:
    adapter = CoinGecko()
    assert TRENDING.dataset_id in adapter.capabilities.datasets


# --------------------------------------------------------------------------- Blockchair small-tx


def test_first_request_small_output_count_rejects_non_btc_subject() -> None:
    adapter = Blockchair()
    with pytest.raises(ProviderNotConfiguredError):
        adapter.first_request(
            SMALL_OUTPUT_COUNT.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "ETH")
        )


def test_first_request_small_output_count_builds_count_aggregation() -> None:
    adapter = Blockchair()
    window = FetchWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 3, tzinfo=UTC), "BTC")
    spec = adapter.first_request(SMALL_OUTPUT_COUNT.dataset_id, window)
    assert spec.path == "/bitcoin/outputs"
    assert spec.params["a"] == "date,count()"
    assert "value_usd(0..1000)" in spec.params["q"]
    assert "2026-09-01..2026-09-02" in spec.params["q"]


def test_parse_page_small_output_count_reads_count_rows() -> None:
    adapter = Blockchair()
    window = FetchWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 3, tzinfo=UTC), "BTC")
    spec = adapter.first_request(SMALL_OUTPUT_COUNT.dataset_id, window)
    body = {
        "data": [{"date": "2026-09-01", "count()": 1234}, {"date": "2026-09-02", "count()": 1300}],
        "context": {"code": 200, "rows": 2, "total_rows": 2},
    }
    records = adapter.parse_page(spec, raw("blockchair", "/bitcoin/outputs", body))
    assert [r.payload["_value"] for r in records] == [1234, 1300]
    assert all(r.dataset_id == SMALL_OUTPUT_COUNT.dataset_id for r in records)


def test_normalise_small_output_count_builds_canonical_observation() -> None:
    adapter = Blockchair()
    window = FetchWindow(datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 3, tzinfo=UTC), "BTC")
    spec = adapter.first_request(SMALL_OUTPUT_COUNT.dataset_id, window)
    body = {
        "data": [{"date": "2026-09-01", "count()": 1234}],
        "context": {"code": 200, "rows": 1, "total_rows": 1},
    }
    (record,) = adapter.parse_page(spec, raw("blockchair", "/bitcoin/outputs", body))
    obs = adapter.normalise(record, ctx(SMALL_OUTPUT_COUNT))
    assert isinstance(obs, CanonicalObservation)
    assert obs.asset == "BTC"
    assert obs.value == Decimal(1234)
    assert obs.event_time == datetime(2026, 9, 1, tzinfo=UTC)
    assert obs.quality_status is QualityStatus.OK


def test_capabilities_include_small_output_count_dataset() -> None:
    adapter = Blockchair()
    assert SMALL_OUTPUT_COUNT.dataset_id in adapter.capabilities.datasets
