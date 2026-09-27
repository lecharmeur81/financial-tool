"""Unit tests for cfi.similarity.outcomes — forward returns, maximum drawdown, and the
distribution summary. Includes this phase's explicit look-ahead-bias tests (TODO.md's own
suggestion for Phase 15/16: build a deliberate look-ahead leak into a test fixture and prove the
leakage tests catch it)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.market_structure.metrics import Bar
from cfi.similarity.outcomes import build_distribution, forward_return, max_drawdown

ANCHOR = datetime(2024, 1, 1, tzinfo=UTC)


def _bar(days: int, close: str) -> Bar:
    return Bar(
        time=ANCHOR + timedelta(days=days),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=None,
    )


# --------------------------------------------------------------------------- forward_return


def test_forward_return_computes_pct_change_when_target_has_elapsed() -> None:
    bars = [_bar(0, "100"), _bar(7, "110")]
    as_of = ANCHOR + timedelta(days=30)
    result = forward_return(bars, anchor=ANCHOR, horizon_days=7, as_of=as_of)
    assert result.status == "ok"
    assert result.value_pct == Decimal("10.00")


def test_forward_return_is_not_yet_known_when_horizon_has_not_elapsed_by_as_of() -> None:
    """Look-ahead-bias test: a 30-day forward return must never be produced when the query's own
    as_of is less than 30 days after the analogue date, even if bars beyond as_of exist in the
    fixture (a deliberate leak — see the leakage test below)."""
    bars = [_bar(0, "100"), _bar(30, "999")]  # a "future" bar the function must not use
    as_of = ANCHOR + timedelta(days=10)  # only 10 days have elapsed
    result = forward_return(bars, anchor=ANCHOR, horizon_days=30, as_of=as_of)
    assert result.status == "not_yet_known"
    assert result.value_pct is None
    assert "not yet knowable" in (result.reason or "")


def test_forward_return_leakage_test_deliberate_leak_is_caught() -> None:
    """A deliberately leaky fixture: bars include a data point dated AFTER as_of (simulating a
    provider or test double that (wrongly) returned future data). The function must still refuse
    to report the 90-day return, proving it gates on ``as_of`` rather than on what happens to be
    present in ``bars`` (R4)."""
    leaky_bars = [
        _bar(0, "100"),
        _bar(45, "150"),  # within as_of, not the target
        _bar(90, "50000"),  # the target bar, but it lies AFTER as_of below — a planted leak
    ]
    as_of = ANCHOR + timedelta(days=45)  # only 45 of the 90 days have actually elapsed
    result = forward_return(leaky_bars, anchor=ANCHOR, horizon_days=90, as_of=as_of)
    assert result.status == "not_yet_known"
    assert result.value_pct is None


def test_forward_return_unavailable_when_no_bars_cover_the_dates() -> None:
    as_of = ANCHOR + timedelta(days=30)
    result = forward_return([], anchor=ANCHOR, horizon_days=7, as_of=as_of)
    assert result.status == "unavailable"


# --------------------------------------------------------------------------- max_drawdown


def test_max_drawdown_finds_the_largest_peak_to_trough_decline() -> None:
    bars = [
        _bar(0, "100"),
        _bar(10, "120"),  # new peak
        _bar(20, "90"),  # -25% from peak
        _bar(30, "150"),  # recovers past prior peak
        _bar(40, "140"),  # -6.67% from new peak — smaller than the -25% above
    ]
    as_of = ANCHOR + timedelta(days=90)
    result = max_drawdown(bars, anchor=ANCHOR, window_days=90, as_of=as_of)
    assert result.status == "ok"
    assert result.value_pct == Decimal("-25.00")
    assert result.partial is False


def test_max_drawdown_is_partial_and_never_uses_bars_after_as_of() -> None:
    """Look-ahead-bias test: a bar dated after as_of (a crash that hasn't 'happened yet' relative
    to the query) must not affect the reported drawdown."""
    bars = [
        _bar(0, "100"),
        _bar(10, "110"),
        _bar(89, "1"),  # a planted future crash, dated after as_of below
    ]
    as_of = ANCHOR + timedelta(days=20)  # window is 90 days; only 20 have elapsed
    result = max_drawdown(bars, anchor=ANCHOR, window_days=90, as_of=as_of)
    assert result.status == "ok"
    assert result.partial is True
    # Only the first two bars (through day 20) may contribute — the planted crash at day 89 must
    # not appear in the computed drawdown.
    assert result.value_pct == Decimal("0.00")


def test_max_drawdown_not_yet_known_when_window_has_not_begun_to_elapse() -> None:
    result = max_drawdown([_bar(0, "100")], anchor=ANCHOR, window_days=90, as_of=ANCHOR)
    assert result.status == "not_yet_known"


# --------------------------------------------------------------------------- build_distribution


def test_build_distribution_insufficient_when_below_min_sample() -> None:
    result = build_distribution([Decimal(1), Decimal(2)], horizon_days=30, min_sample=3)
    assert result.status == "insufficient_data"
    assert result.count == 2


def test_build_distribution_reports_range_not_a_single_prediction() -> None:
    values = [Decimal(v) for v in (-10, -5, 0, 5, 10, 20)]
    result = build_distribution(values, horizon_days=30, min_sample=3)
    assert result.status == "ok"
    assert result.count == 6
    assert result.min_pct == Decimal(-10)
    assert result.max_pct == Decimal(20)
    assert result.median_pct is not None
