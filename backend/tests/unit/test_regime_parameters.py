"""Unit tests for cfi.regime.parameters: the versioned regime-definition registry itself."""

from __future__ import annotations

from decimal import Decimal

import pytest

from cfi.regime import parameters as rp


def test_current_version_resolves_and_unknown_version_is_a_hard_error() -> None:
    params = rp.parameters()
    assert params.version == rp.CURRENT_VERSION
    assert rp.parameters(rp.CURRENT_VERSION) is params
    with pytest.raises(KeyError):
        rp.parameters("regime_classifier_v99")


def test_exactly_six_substantive_regimes_are_defined() -> None:
    params = rp.parameters()
    assert len(params.regimes) == 6
    ids = {r.regime_id for r in params.regimes}
    assert ids == {
        "accumulation",
        "recovery",
        "expansion",
        "euphoria",
        "distribution",
        "capitulation",
    }
    assert "mixed_unclear" not in ids  # the classifier's own fallback, never a defined regime


def test_every_regimes_condition_weights_sum_to_one() -> None:
    for regime in rp.parameters().regimes:
        total = sum((c.weight for c in regime.conditions), Decimal(0))
        assert total == Decimal(1), f"{regime.regime_id} weights sum to {total}, expected 1"


def test_every_condition_has_a_threshold_or_expected_set() -> None:
    for regime in rp.parameters().regimes:
        for c in regime.conditions:
            if c.comparator == "categorical":
                assert c.expected
            elif c.comparator == "between":
                assert c.threshold is not None
                assert c.threshold_high is not None
            else:
                assert c.threshold is not None
