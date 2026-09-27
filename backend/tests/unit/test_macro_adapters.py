"""FRED provider adapter (Phase 11): request building, parsing (including FRED's own '.'
missing-value marker) and normalisation, and the availability-rule wiring for each period kind
(no network)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.core.errors import DataValidationError, ProviderNotConfiguredError, SchemaMismatchError
from cfi.domain.datasets import DatasetSpec
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.macro.universe import CPI, FED_FUNDS_TARGET_UPPER, US_SUBJECT, UST_YIELD_10Y, VIX
from cfi.providers.base import FetchWindow, NormaliseContext, RawResponse
from cfi.providers.fred import FRED

NOW = datetime(2026, 9, 27, 12, tzinfo=UTC)
WINDOW = FetchWindow(NOW - timedelta(days=10), NOW, US_SUBJECT)


def raw(path: str, body: object, params: Mapping[str, str] | None = None) -> RawResponse:
    return RawResponse(
        "fred", path, params or {}, NOW, 200, "application/json", json.dumps(body).encode()
    )


def ctx(dataset: DatasetSpec, at: datetime = NOW) -> NormaliseContext:
    return NormaliseContext(dataset=dataset, ingested_at=at, raw_ref=1)


def test_first_request_builds_series_observations_request() -> None:
    adapter = FRED()
    spec = adapter.first_request(VIX.dataset_id, WINDOW)
    assert spec.path == "/series/observations"
    assert spec.params["series_id"] == "VIXCLS"
    assert spec.params["file_type"] == "json"
    assert spec.params["observation_start"] == WINDOW.start.date().isoformat()
    assert spec.params["observation_end"] == WINDOW.end.date().isoformat()


def test_first_request_rejects_unmapped_dataset() -> None:
    adapter = FRED()
    with pytest.raises(ProviderNotConfiguredError):
        adapter.first_request("macro.not_a_real_dataset", WINDOW)


def test_parse_reads_observations() -> None:
    adapter = FRED()
    spec = adapter.first_request(VIX.dataset_id, WINDOW)
    body = {
        "observations": [
            {"date": "2026-09-24", "value": "16.50"},
            {"date": "2026-09-25", "value": "17.10"},
        ]
    }
    records = adapter.parse_page(spec, raw("/series/observations", body, spec.params))
    assert [r.payload["date"] for r in records] == ["2026-09-24", "2026-09-25"]
    assert all(r.dataset_id == VIX.dataset_id for r in records)


def test_parse_rejects_response_without_observations_list() -> None:
    adapter = FRED()
    spec = adapter.first_request(VIX.dataset_id, WINDOW)
    with pytest.raises(SchemaMismatchError, match="observations"):
        adapter.parse_page(spec, raw("/series/observations", {"count": 0}, spec.params))


def test_parse_rejects_observation_missing_required_field() -> None:
    adapter = FRED()
    spec = adapter.first_request(VIX.dataset_id, WINDOW)
    body = {"observations": [{"date": "2026-09-24"}]}  # no value
    with pytest.raises(SchemaMismatchError, match="value"):
        adapter.parse_page(spec, raw("/series/observations", body, spec.params))


def test_parse_via_public_parse_delegates_to_parse_page() -> None:
    """``parse()`` (the abstract interface method) reconstructs series_id from the raw response's
    own request_params — no external state needed, unlike a caller bypassing parse_page."""
    adapter = FRED()
    spec = adapter.first_request(VIX.dataset_id, WINDOW)
    body = {"observations": [{"date": "2026-09-24", "value": "16.50"}]}
    records = adapter.parse(raw("/series/observations", body, spec.params))
    assert records[0].dataset_id == VIX.dataset_id


def test_normalise_builds_canonical_observation_for_daily_series() -> None:
    adapter = FRED()
    spec = adapter.first_request(VIX.dataset_id, WINDOW)
    body = {"observations": [{"date": "2026-09-01", "value": "16.50"}]}
    (record,) = adapter.parse_page(spec, raw("/series/observations", body, spec.params))
    obs = adapter.normalise(record, ctx(VIX, at=datetime(2026, 9, 3, tzinfo=UTC)))
    assert isinstance(obs, CanonicalObservation)
    assert obs.asset == US_SUBJECT
    assert obs.value == Decimal("16.50")
    assert obs.event_time == datetime(2026, 9, 1, tzinfo=UTC)
    assert obs.quality_status is QualityStatus.OK
    # period_end_plus: event_time + period_length (1 day) + delay (1 day) = 2026-09-03, exactly
    # at the 2026-09-03 ingest (not yet final any earlier).
    assert obs.available_at == datetime(2026, 9, 3, tzinfo=UTC)
    assert obs.available_at_estimated is True


def test_normalise_marks_fred_missing_marker_as_missing() -> None:
    adapter = FRED()
    spec = adapter.first_request(VIX.dataset_id, WINDOW)
    body = {"observations": [{"date": "2026-09-01", "value": "."}]}
    (record,) = adapter.parse_page(spec, raw("/series/observations", body, spec.params))
    obs = adapter.normalise(record, ctx(VIX))
    assert obs.value is None
    assert obs.quality_status is QualityStatus.MISSING
    assert obs.quality_note is not None


def test_normalise_rejects_unparseable_date() -> None:
    adapter = FRED()
    spec = adapter.first_request(VIX.dataset_id, WINDOW)
    body = {"observations": [{"date": "not-a-date", "value": "16.50"}]}
    (record,) = adapter.parse_page(spec, raw("/series/observations", body, spec.params))
    with pytest.raises(DataValidationError, match="unparseable"):
        adapter.normalise(record, ctx(VIX))


def test_normalise_monthly_series_uses_event_time_plus_estimated_delay() -> None:
    """CPI: event_time = reference month start; available_at is estimated ~45 days later, not
    FRED's own realtime_start (see cfi.macro.universe's 'Point-in-time integrity' note)."""
    adapter = FRED()
    spec = adapter.first_request(CPI.dataset_id, WINDOW)
    body = {"observations": [{"date": "2026-01-01", "value": "320.5"}]}
    (record,) = adapter.parse_page(spec, raw("/series/observations", body, spec.params))
    obs = adapter.normalise(record, ctx(CPI, at=datetime(2026, 6, 1, tzinfo=UTC)))
    assert obs.event_time == datetime(2026, 1, 1, tzinfo=UTC)
    assert obs.available_at == datetime(2026, 2, 15, tzinfo=UTC)  # +45 days
    assert obs.available_at_estimated is True


def test_normalise_event_series_uses_one_day_estimated_delay() -> None:
    adapter = FRED()
    spec = adapter.first_request(FED_FUNDS_TARGET_UPPER.dataset_id, WINDOW)
    body = {"observations": [{"date": "2026-09-17", "value": "4.25"}]}
    (record,) = adapter.parse_page(spec, raw("/series/observations", body, spec.params))
    obs = adapter.normalise(
        record, ctx(FED_FUNDS_TARGET_UPPER, at=datetime(2026, 9, 20, tzinfo=UTC))
    )
    assert obs.event_time == datetime(2026, 9, 17, tzinfo=UTC)
    assert obs.available_at == datetime(2026, 9, 18, tzinfo=UTC)


def test_capabilities_include_every_mapped_dataset() -> None:
    adapter = FRED()
    assert UST_YIELD_10Y.dataset_id in adapter.capabilities.datasets
    assert VIX.dataset_id in adapter.capabilities.datasets
    assert CPI.dataset_id in adapter.capabilities.datasets


def test_auth_is_required_query_key_not_optional() -> None:
    from cfi.domain.enums import AuthType

    auth = FRED().capabilities.auth
    assert auth.type is AuthType.API_KEY_QUERY
    assert auth.optional is False
    assert auth.name == "api_key"
