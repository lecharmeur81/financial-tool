from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from cfi.core.errors import ProviderNotConfiguredError
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.providers.base import FetchWindow, NormaliseContext, ProviderRecord, RawResponse
from cfi.providers.mock import MOCK_DATASET
from cfi.providers.registry import ProviderRegistry
from cfi.providers.stub import StubProvider

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _obs(**overrides: Any) -> CanonicalObservation:
    fields: dict[str, Any] = {
        "dataset_id": "test_dataset",
        "metric": "test_metric",
        "asset": "BTC",
        "subject_ref": "BTC",
        "period": "1d",
        "unit": "usd",
        "event_time": T0,
        "available_at": T0 + timedelta(days=1),
        "available_at_estimated": False,
        "ingested_at": T0 + timedelta(days=1, minutes=5),
        "value": Decimal("1.5"),
        "source_provider": "test",
        "original_source": "unknown",
        "quality_status": QualityStatus.OK,
        "pit_reliability": PitReliability.NATIVE,
    }
    fields.update(overrides)
    return CanonicalObservation(**fields)


# ------------------------------------------------------------------ stub provider


def test_stub_request_refuses_instead_of_inventing_data() -> None:
    stub = StubProvider()
    with pytest.raises(ProviderNotConfiguredError, match="stub"):
        stub.first_request("any_dataset", FetchWindow(T0, T0 + timedelta(hours=1)))


def test_stub_parse_and_normalise_refuse() -> None:
    stub = StubProvider()
    raw = RawResponse("stub", "/x", {}, T0, 200, "application/json", b"{}")
    with pytest.raises(ProviderNotConfiguredError):
        stub.parse(raw)
    ctx = NormaliseContext(dataset=MOCK_DATASET, ingested_at=T0, raw_ref=None)
    with pytest.raises(ProviderNotConfiguredError):
        stub.normalise(ProviderRecord("stub", "d"), ctx)


def test_stub_declares_no_datasets() -> None:
    stub = StubProvider()
    assert stub.capabilities.datasets == frozenset()
    assert stub.capabilities.terms_verified is False
    assert not stub.supports("anything")


# ------------------------------------------------------------------ registry


def test_registry_lookup_and_unknown_provider() -> None:
    registry = ProviderRegistry()
    registry.register(StubProvider("a"))
    registry.register(StubProvider("b"))
    assert registry.ids() == ["a", "b"]
    assert registry.get("a").provider_id == "a"
    with pytest.raises(ProviderNotConfiguredError):
        registry.get("missing")
    assert registry.providers_for("some_dataset") == []


def test_registry_rejects_duplicates() -> None:
    registry = ProviderRegistry()
    registry.register(StubProvider("a"))
    with pytest.raises(ValueError, match="already registered"):
        registry.register(StubProvider("a"))


# ------------------------------------------------------------------ value objects


def test_fetch_window_requires_order_and_awareness() -> None:
    with pytest.raises(ValueError, match="earlier"):
        FetchWindow(T0, T0)
    with pytest.raises(ValueError, match="timezone-aware"):
        FetchWindow(datetime(2026, 1, 1), T0)  # noqa: DTZ001


def test_raw_response_normalises_to_utc() -> None:
    manila = timezone(timedelta(hours=8))
    raw = RawResponse("p", "/x", {}, datetime(2026, 9, 1, 8, tzinfo=manila), 200, "t", b"")
    assert raw.received_at == T0


# ------------------------------------------------------------------ canonical observation (R3)


def test_valid_observation() -> None:
    obs = _obs()
    assert obs.value == Decimal("1.5")
    assert obs.event_time.tzinfo is UTC


def test_missing_value_requires_missing_status() -> None:
    with pytest.raises(ValueError, match="missing"):
        _obs(value=None)


def test_missing_status_cannot_carry_a_value() -> None:
    with pytest.raises(ValueError, match="missing"):
        _obs(quality_status=QualityStatus.MISSING, quality_note="not received")


def test_missing_observation_is_representable() -> None:
    obs = _obs(
        value=None, quality_status=QualityStatus.MISSING, quality_note="provider returned no row"
    )
    assert obs.value is None


def test_non_ok_status_requires_a_note() -> None:
    with pytest.raises(ValueError, match="quality_note"):
        _obs(quality_status=QualityStatus.STALE)


def test_confidence_bounds() -> None:
    with pytest.raises(ValueError, match="confidence"):
        _obs(confidence=Decimal("1.1"))
    assert _obs(confidence=Decimal("0.4")).confidence == Decimal("0.4")


def test_naive_timestamps_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _obs(event_time=datetime(2026, 9, 1))  # noqa: DTZ001


def test_original_source_must_be_explicit() -> None:
    with pytest.raises(ValueError, match="original_source"):
        _obs(original_source="")
