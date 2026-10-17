"""The memoised ``realized_volatility_series`` must be output-identical to the implementation it
replaced, which is kept below verbatim as ``reference_series``.

"Identical" is checked on ``repr`` (``Decimal('1.0')`` and ``Decimal('1.00')`` compare equal but are
different outputs), under the default Decimal context, under other precisions and rounding modes,
with warm caches, with overlapping/shifted bar histories (what repeated snapshots look like), and
with inputs that make the original raise.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_UP,
    Decimal,
    Inexact,
    localcontext,
)
from typing import Any

import pytest

from cfi.market_structure import metrics as m

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def reference_series(
    bars: Sequence[m.Bar], window: int = m.VOLATILITY_WINDOW
) -> list[tuple[datetime, Decimal]]:
    """The pre-memoisation implementation, verbatim."""
    closes = [b.close for b in bars]
    log_returns = [
        (closes[i] / closes[i - 1]).ln() for i in range(1, len(closes)) if closes[i - 1] > 0
    ]
    out = []
    for i in range(window, len(log_returns) + 1):
        chunk = log_returns[i - window : i]
        mean = sum(chunk, Decimal(0)) / window
        variance = sum(((x - mean) ** 2 for x in chunk), Decimal(0)) / (window - 1)
        annualized = variance.sqrt() * m.ANNUALISATION_DAYS.sqrt()
        out.append((bars[i].time, annualized))
    return out


def make_bars(n: int, seed: int, *, zero_at: int | None = None) -> list[m.Bar]:
    """A random walk whose closes use mixed decimal places (and so mixed exponents), repeated
    closes (ratio exactly 1) and trailing zeros."""
    rng = random.Random(seed)  # noqa: S311 - deterministic fixture data
    price = 100.0
    bars = []
    for i in range(n):
        if rng.random() > 0.1:  # 10 % of days repeat the previous close
            price *= 1 + rng.uniform(-0.04, 0.04)
        places = rng.choice([0, 1, 2, 2, 3, 4, 6])
        close = Decimal(f"{price:.{places}f}")
        if zero_at == i:
            close = Decimal(0)
        bars.append(m.Bar(T0 + timedelta(days=i), close, close, close, close, Decimal(1)))
    return bars


def outcome(fn: Callable[[], list[tuple[datetime, Decimal]]]) -> Any:
    try:
        return [(t, repr(v)) for t, v in fn()]
    except Exception as exc:  # the exception type is the comparison
        return ("raised", type(exc))


@pytest.fixture(autouse=True)
def fresh_caches() -> Any:
    m._ln_of.cache_clear()
    m._window_annualized.cache_clear()
    yield
    m._ln_of.cache_clear()
    m._window_annualized.cache_clear()


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_default_window_matches_reference_cold_and_warm(seed: int) -> None:
    bars = make_bars(431, seed)
    expected = outcome(lambda: reference_series(bars))
    assert len(expected) == 401
    assert outcome(lambda: m.realized_volatility_series(bars)) == expected  # cold
    assert outcome(lambda: m.realized_volatility_series(bars)) == expected  # warm


@pytest.mark.parametrize("window", [2, 5, 14, 30, 60])
def test_other_windows_match_reference(window: int) -> None:
    bars = make_bars(200, 11)
    assert outcome(lambda: m.realized_volatility_series(bars, window)) == outcome(
        lambda: reference_series(bars, window)
    )


def test_shifted_overlapping_histories_match_reference_and_reuse_windows() -> None:
    base = make_bars(700, 7)
    for offset in (0, 1, 7, 14, 91, 250):  # like snapshots a few days/weeks apart
        bars = base[offset : offset + 431]
        assert outcome(lambda b=bars: m.realized_volatility_series(b)) == outcome(  # type: ignore[misc]
            lambda b=bars: reference_series(b)  # type: ignore[misc]
        )
    info = m._window_annualized.cache_info()
    assert info.hits > info.misses  # the overlap is actually being reused
    assert info.currsize <= m._WINDOW_MEMO_SIZE


def test_warm_call_is_served_from_the_caches() -> None:
    bars = make_bars(431, 9)
    m.realized_volatility_series(bars)
    ln0, win0 = m._ln_of.cache_info(), m._window_annualized.cache_info()
    m.realized_volatility_series(bars)
    ln1, win1 = m._ln_of.cache_info(), m._window_annualized.cache_info()
    assert ln1.misses == ln0.misses
    assert win1.misses == win0.misses
    assert win1.hits - win0.hits == 401


def test_realized_volatility_reading_is_unchanged() -> None:
    bars = make_bars(431, 21)
    first = m.realized_volatility(bars)
    second = m.realized_volatility(bars)  # warm
    assert first == second
    series = reference_series(bars)
    assert repr(first.annualized_pct) == repr(series[-1][1])
    assert first.window_readings == min(len(series), m.VOLATILITY_PERCENTILE_WINDOW)


@pytest.mark.parametrize(
    ("prec", "rounding"), [(10, ROUND_DOWN), (50, ROUND_HALF_EVEN), (28, ROUND_UP), (5, ROUND_UP)]
)
def test_results_follow_the_active_decimal_context(prec: int, rounding: str) -> None:
    bars = make_bars(120, 3)
    default_expected = outcome(lambda: reference_series(bars))
    assert outcome(lambda: m.realized_volatility_series(bars)) == default_expected
    with localcontext() as ctx:
        ctx.prec = prec
        ctx.rounding = rounding
        expected = outcome(lambda: reference_series(bars))
        assert outcome(lambda: m.realized_volatility_series(bars)) == expected  # cold for ctx
        assert outcome(lambda: m.realized_volatility_series(bars)) == expected  # warm for ctx
    # the other context's cached entries never leak back
    assert outcome(lambda: m.realized_volatility_series(bars)) == default_expected


def test_enabled_traps_are_part_of_the_cache_key() -> None:
    bars = make_bars(60, 5)
    default_expected = outcome(lambda: reference_series(bars))
    assert outcome(lambda: m.realized_volatility_series(bars)) == default_expected  # warms caches
    with localcontext() as ctx:
        ctx.traps[Inexact] = True
        expected = outcome(lambda: reference_series(bars))
        assert expected == ("raised", Inexact)
        assert outcome(lambda: m.realized_volatility_series(bars)) == expected


def test_inputs_that_make_the_original_raise_still_raise_the_same_way() -> None:
    bars = make_bars(60, 5, zero_at=30)  # a zero close gives ln(0) = -Infinity downstream
    expected = outcome(lambda: reference_series(bars))
    assert outcome(lambda: m.realized_volatility_series(bars)) == expected
    assert outcome(lambda: m.realized_volatility_series(bars)) == expected  # nothing was cached
    for bad_window in (0, 1):
        ok = make_bars(40, 6)
        assert outcome(lambda w=bad_window, b=ok: m.realized_volatility_series(b, w)) == outcome(  # type: ignore[misc]
            lambda w=bad_window, b=ok: reference_series(b, w)  # type: ignore[misc]
        )


def test_zero_previous_close_is_skipped_exactly_as_before() -> None:
    bars = make_bars(80, 8)
    bars[10] = m.Bar(bars[10].time, Decimal(0), Decimal(0), Decimal(0), Decimal(0), Decimal(1))
    # closes[10] == 0 makes ratio[10] == 0 -> -Infinity; closes[11]/closes[10] is skipped.
    assert outcome(lambda: m.realized_volatility_series(bars)) == outcome(
        lambda: reference_series(bars)
    )


@pytest.mark.parametrize(
    "text", ["1", "1.0", "1.00", "1E+0", "0.98", "0.980", "1.0000001", "2.5E+1"]
)
def test_ln_cache_distinguishes_representations(text: str) -> None:
    key = m._decimal_context_key()
    assert repr(m._ln_of(text, key)) == repr(Decimal(text).ln())
    assert repr(m._ln_of(text, key)) == repr(Decimal(text).ln())  # warm


def test_caches_are_bounded() -> None:
    key = m._decimal_context_key()
    assert m._ln_of.cache_info().maxsize == m._LN_MEMO_SIZE
    assert m._window_annualized.cache_info().maxsize == m._WINDOW_MEMO_SIZE
    for i in range(m._LN_MEMO_SIZE + 300):
        m._ln_of(f"1.{i:07d}", key)
    assert m._ln_of.cache_info().currsize == m._LN_MEMO_SIZE
    for i in range(m._WINDOW_MEMO_SIZE + 300):
        texts = tuple(f"0.{i:06d}{j:02d}" for j in range(m.VOLATILITY_WINDOW))
        m._window_annualized(texts, m.VOLATILITY_WINDOW, key)
    assert m._window_annualized.cache_info().currsize == m._WINDOW_MEMO_SIZE
