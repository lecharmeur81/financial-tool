"""DefiLlama stablecoins adapter: requests, parsing, normalisation (no network)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.core.errors import DataValidationError, SchemaMismatchError
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.liquidity.universe import SUPPLY, TOTAL_SUBJECT, supply_ref
from cfi.providers.base import FetchWindow, NormaliseContext, RawResponse
from cfi.providers.defillama import DefiLlama

NOW = datetime(2026, 9, 26, 12, tzinfo=UTC)
WINDOW = FetchWindow(NOW - timedelta(days=7), NOW)


def raw(body: object, params: dict[str, str] | None = None) -> RawResponse:
    return RawResponse(
        "defillama",
        "/stablecoincharts/all",
        params or {},
        NOW,
        200,
        "application/json",
        json.dumps(body).encode(),
    )


def ctx(at: datetime = NOW) -> NormaliseContext:
    return NormaliseContext(dataset=SUPPLY, ingested_at=at, raw_ref=1)


def row(date_s: str, pegged: object) -> dict[str, object]:
    return {"date": date_s, "totalCirculating": {"peggedUSD": pegged}}


# --------------------------------------------------------------------------- first_request


def test_first_request_total_subject_has_no_stablecoin_param() -> None:
    adapter = DefiLlama()
    spec = adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "TOTAL"))
    assert spec.path == "/stablecoincharts/all"
    assert spec.params == {}
    assert spec.state["subject"] == "TOTAL"


def test_first_request_usdt_subject_maps_to_defillama_id() -> None:
    adapter = DefiLlama()
    spec = adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "USDT"))
    assert spec.params == {"stablecoin": "1"}


def test_first_request_usdc_subject_maps_to_defillama_id() -> None:
    adapter = DefiLlama()
    spec = adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "USDC"))
    assert spec.params == {"stablecoin": "2"}


def test_first_request_unknown_subject_is_rejected() -> None:
    adapter = DefiLlama()
    with pytest.raises(ValueError, match="no stablecoin subject"):
        adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "DAI"))


def test_first_request_no_subject_is_rejected() -> None:
    adapter = DefiLlama()
    with pytest.raises(ValueError, match="no stablecoin subject"):
        adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, None))


# --------------------------------------------------------------------------- parse / parse_page


def test_parse_is_not_implemented_rows_go_through_parse_page() -> None:
    adapter = DefiLlama()
    with pytest.raises(NotImplementedError):
        adapter.parse(raw([]))


def test_parse_page_filters_to_the_requested_window() -> None:
    adapter = DefiLlama()
    window = FetchWindow(
        datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 23, tzinfo=UTC), "TOTAL"
    )
    spec = adapter.first_request(SUPPLY.dataset_id, window)
    start_s, end_s = int(window.start.timestamp()), int(window.end.timestamp())
    body = [
        row(str(start_s - 86400), 100),  # one day before the window — excluded
        row(str(start_s), 200),  # at the window start — included
        row(str(start_s + 86400), 300),  # inside the window — included
        row(str(end_s), 400),  # at the window end — excluded (half-open)
    ]
    records = adapter.parse_page(spec, raw(body))
    values = [r.payload["value"] for r in records]
    assert values == [200, 300]


def test_parse_page_rejects_row_missing_required_fields() -> None:
    adapter = DefiLlama()
    spec = adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "TOTAL"))
    with pytest.raises(SchemaMismatchError, match="must have 'date'"):
        adapter.parse_page(spec, raw([{"date": "123"}]))


def test_parse_page_rejects_non_digit_date() -> None:
    adapter = DefiLlama()
    spec = adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "TOTAL"))
    with pytest.raises(SchemaMismatchError, match="digit string"):
        adapter.parse_page(spec, raw([row("2026-09-20", 100)]))


def test_parse_page_rejects_missing_pegged_usd() -> None:
    adapter = DefiLlama()
    spec = adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "TOTAL"))
    body = [{"date": str(int(WINDOW.start.timestamp())), "totalCirculating": {}}]
    with pytest.raises(SchemaMismatchError, match="peggedUSD"):
        adapter.parse_page(spec, raw(body))


def test_parse_page_rejects_response_that_is_not_an_array() -> None:
    adapter = DefiLlama()
    spec = adapter.first_request(SUPPLY.dataset_id, FetchWindow(WINDOW.start, WINDOW.end, "TOTAL"))
    with pytest.raises(SchemaMismatchError, match="JSON array"):
        adapter.parse_page(spec, raw({"not": "a list"}))


# --------------------------------------------------------------------------- normalise


def test_normalise_builds_a_canonical_observation() -> None:
    adapter = DefiLlama()
    window = FetchWindow(
        datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 27, tzinfo=UTC), "USDT"
    )
    spec = adapter.first_request(SUPPLY.dataset_id, window)
    body = [row(str(int(window.start.timestamp())), "123456789.5")]
    (record,) = adapter.parse_page(spec, raw(body))
    obs = adapter.normalise(record, ctx())
    assert isinstance(obs, CanonicalObservation)
    assert obs.asset == "USDT"
    assert obs.subject_ref == supply_ref("USDT")
    assert obs.value == Decimal("123456789.5")
    assert obs.event_time == window.start
    assert obs.quality_status is QualityStatus.OK
    assert obs.source_provider == "defillama"
    assert obs.original_source == "defillama"


def test_normalise_flags_negative_supply_as_suspect() -> None:
    adapter = DefiLlama()
    window = FetchWindow(
        datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 27, tzinfo=UTC), "TOTAL"
    )
    spec = adapter.first_request(SUPPLY.dataset_id, window)
    body = [row(str(int(window.start.timestamp())), -5)]
    (record,) = adapter.parse_page(spec, raw(body))
    obs = adapter.normalise(record, ctx())
    assert obs.quality_status is QualityStatus.SUSPECT
    assert obs.quality_note is not None
    assert "negative" in obs.quality_note


def test_normalise_rejects_non_numeric_value() -> None:
    adapter = DefiLlama()
    window = FetchWindow(
        datetime(2026, 9, 20, tzinfo=UTC), datetime(2026, 9, 27, tzinfo=UTC), "TOTAL"
    )
    spec = adapter.first_request(SUPPLY.dataset_id, window)
    body = [row(str(int(window.start.timestamp())), "not-a-number")]
    (record,) = adapter.parse_page(spec, raw(body))
    with pytest.raises(DataValidationError):
        adapter.normalise(record, ctx())


def test_capabilities_declare_only_the_supply_dataset() -> None:
    adapter = DefiLlama()
    assert adapter.capabilities.datasets == frozenset({SUPPLY.dataset_id})
    assert adapter.provider_id == "defillama"
    assert adapter.supports(SUPPLY.dataset_id)


def test_total_subject_constant_is_not_a_defillama_id() -> None:
    # sanity check that the module's TOTAL_SUBJECT constant matches universe's
    assert TOTAL_SUBJECT == "TOTAL"
