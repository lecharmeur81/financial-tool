"""Unit tests for cfi.backtest.versioning — reproducibility fields (R7: every backtest must be
reproducible)."""

from __future__ import annotations

from datetime import UTC, datetime

from cfi.backtest.versioning import code_version, dataset_version

D1 = datetime(2024, 1, 1, tzinfo=UTC)
D2 = datetime(2024, 6, 1, tzinfo=UTC)


def test_code_version_returns_a_non_empty_string() -> None:
    assert isinstance(code_version(), str)
    assert code_version() != ""


def test_dataset_version_is_deterministic_for_identical_inputs() -> None:
    kwargs = dict(
        asset="BTC", start=D1, end=D2, as_of=D2, knowledge_time=D2, provider_id="coinbase"
    )
    assert dataset_version(**kwargs) == dataset_version(**kwargs)  # type: ignore[arg-type]


def test_dataset_version_changes_when_any_input_changes() -> None:
    base = dataset_version(
        asset="BTC", start=D1, end=D2, as_of=D2, knowledge_time=D2, provider_id="coinbase"
    )
    different_asset = dataset_version(
        asset="ETH", start=D1, end=D2, as_of=D2, knowledge_time=D2, provider_id="coinbase"
    )
    different_as_of = dataset_version(
        asset="BTC", start=D1, end=D2, as_of=D1, knowledge_time=D2, provider_id="coinbase"
    )
    different_provider = dataset_version(
        asset="BTC", start=D1, end=D2, as_of=D2, knowledge_time=D2, provider_id="binance"
    )
    assert len({base, different_asset, different_as_of, different_provider}) == 4


def test_dataset_version_is_a_16_character_hex_fingerprint() -> None:
    value = dataset_version(
        asset="BTC", start=D1, end=D2, as_of=D2, knowledge_time=D2, provider_id="coinbase"
    )
    assert len(value) == 16
    int(value, 16)  # raises ValueError if not valid hex
