"""`cfi.paper.pnl` — deterministic, DB-free P&L calculations (Phase 24 spec "P&L calculations" /
"Entry and exit": "Observed market price -> simulated execution price -> calculated P&L")."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cfi.backtest.costs import COST_MODEL_V1, COST_MODEL_V2
from cfi.divergence.metrics import SeriesPoint
from cfi.paper.pnl import (
    Direction,
    PnLResult,
    calculate_pnl,
    current_price,
    execution_price,
    execution_side,
    max_favorable_adverse,
)

NOW = datetime(2026, 10, 3, 12, 0, 0, tzinfo=UTC)
FLAT = COST_MODEL_V1  # fee_bps=10, slippage_bps=5, no participation scaling — easiest to hand-check


# ------------------------------------------------------------------ execution_side / price


def test_long_entry_buys_and_exit_sells() -> None:
    assert execution_side("long", "entry") == "buy"
    assert execution_side("long", "exit") == "sell"


def test_short_entry_sells_and_exit_buys() -> None:
    assert execution_side("short", "entry") == "sell"
    assert execution_side("short", "exit") == "buy"


def test_long_entry_execution_price_is_adverse_upward() -> None:
    price = execution_price(Decimal(100), direction="long", leg="entry", params=FLAT)
    assert price > Decimal(100)


def test_long_exit_execution_price_is_adverse_downward() -> None:
    price = execution_price(Decimal(100), direction="long", leg="exit", params=FLAT)
    assert price < Decimal(100)


def test_short_entry_execution_price_is_adverse_downward() -> None:
    price = execution_price(Decimal(100), direction="short", leg="entry", params=FLAT)
    assert price < Decimal(100)


def test_short_exit_execution_price_is_adverse_upward() -> None:
    price = execution_price(Decimal(100), direction="short", leg="exit", params=FLAT)
    assert price > Decimal(100)


# ---------------------------------------------------------------- current_price (window_reading)


def test_current_price_is_the_latest_point_at_or_before_as_of() -> None:
    points = [
        SeriesPoint(datetime(2026, 10, 1, tzinfo=UTC), Decimal(90)),
        SeriesPoint(datetime(2026, 10, 2, tzinfo=UTC), Decimal(95)),
    ]
    assert current_price(points, NOW) == Decimal(95)


def test_current_price_is_none_when_no_point_is_at_or_before_as_of() -> None:
    points = [SeriesPoint(datetime(2026, 10, 10, tzinfo=UTC), Decimal(95))]
    assert current_price(points, NOW) is None


def test_current_price_is_none_for_empty_series() -> None:
    assert current_price([], NOW) is None


# ------------------------------------------------------------------ calculate_pnl: long


def test_long_winning_trade_gross_pnl_is_positive() -> None:
    result = calculate_pnl(
        direction="long",
        notional=Decimal(10_000),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal("100.05"),
        exit_price_observed=Decimal(110),
        exit_price_execution=Decimal("109.945"),
        params=FLAT,
    )
    # quantity = 10_000 / 100.05 ~= 99.95; gross = quantity * (110 - 100) = ~999.5
    assert result.gross_pnl > 0
    assert result.net_pnl < result.gross_pnl  # costs always reduce net relative to gross
    assert result.slippage_cost > 0
    assert result.fees_total > 0
    # reconciliation: net = gross - slippage - fees, exactly
    assert result.net_pnl == result.gross_pnl - result.slippage_cost - result.fees_total


def test_long_losing_trade_gross_pnl_is_negative() -> None:
    result = calculate_pnl(
        direction="long",
        notional=Decimal(10_000),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal("100.05"),
        exit_price_observed=Decimal(90),
        exit_price_execution=Decimal("89.955"),
        params=FLAT,
    )
    assert result.gross_pnl < 0
    assert result.net_pnl < result.gross_pnl  # costs make a loss even worse


# ------------------------------------------------------------------ calculate_pnl: short


def test_short_winning_trade_gross_pnl_is_positive() -> None:
    result = calculate_pnl(
        direction="short",
        notional=Decimal(10_000),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal("99.95"),
        exit_price_observed=Decimal(90),
        exit_price_execution=Decimal("90.045"),
        params=FLAT,
    )
    # Price fell; a short profits from a fall.
    assert result.gross_pnl > 0


def test_short_losing_trade_gross_pnl_is_negative() -> None:
    result = calculate_pnl(
        direction="short",
        notional=Decimal(10_000),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal("99.95"),
        exit_price_observed=Decimal(110),
        exit_price_execution=Decimal("110.055"),
        params=FLAT,
    )
    assert result.gross_pnl < 0


def test_long_and_short_are_mirror_images_on_the_same_price_move() -> None:
    """A flat price move's gross P&L (pre-cost) for a long is the exact negative of a short's,
    holding size and prices fixed — confirms the ``sign`` term in ``calculate_pnl`` is correct."""
    kwargs = {
        "notional": Decimal(10_000),
        "leverage": Decimal(1),
        "entry_price_observed": Decimal(100),
        "entry_price_execution": Decimal(100),
        "exit_price_observed": Decimal(120),
        "exit_price_execution": Decimal(120),
        "params": COST_MODEL_V1,
    }
    long_result = calculate_pnl(direction="long", **kwargs)  # type: ignore[arg-type]
    short_result = calculate_pnl(direction="short", **kwargs)  # type: ignore[arg-type]
    assert long_result.gross_pnl == -short_result.gross_pnl


# ---------------------------------------------- Phase 34 Finding 1: long/short mirror asymmetry
#
# Root cause: ``calculate_pnl`` sized ``quantity = notional / entry_price_execution``. The
# execution price is direction-dependent (``slipped_price`` via ``execution_price``: adverse
# *upward* for a long's "buy" entry, adverse *downward* for a short's "sell" entry), so a long and
# a short trade with identical *observed* entry/exit prices got different ``quantity`` values —
# which broke the mirror symmetry the module promises for ``gross_pnl`` (computed purely from
# observed prices). The test below reproduces the real bug: unlike
# ``test_long_and_short_are_mirror_images_on_the_same_price_move`` above, which sidesteps the issue
# entirely by setting ``entry_price_execution == entry_price_observed`` (zero slippage), this uses
# genuinely slipped, direction-dependent execution prices computed via ``execution_price`` itself —
# exactly what ``PaperTradingService`` does in production. Fix: size off ``entry_price_observed``.


def _realistic_trade(
    direction: Direction,
    *,
    entry_observed: Decimal,
    exit_observed: Decimal,
    notional: Decimal = Decimal(10_000),
) -> PnLResult:
    """Run ``calculate_pnl`` from identical *observed* prices with genuinely slipped,
    direction-appropriate execution prices computed via ``execution_price`` itself (not an
    artificial equal-price shortcut) — exactly what ``PaperTradingService`` does in production,
    and the realistic scenario Finding 1 was about."""
    return calculate_pnl(
        direction=direction,
        notional=notional,
        leverage=Decimal(1),
        entry_price_observed=entry_observed,
        entry_price_execution=execution_price(
            entry_observed, direction=direction, leg="entry", params=FLAT
        ),
        exit_price_observed=exit_observed,
        exit_price_execution=execution_price(
            exit_observed, direction=direction, leg="exit", params=FLAT
        ),
        params=FLAT,
    )


def test_mirrored_long_and_short_have_equal_and_opposite_gross_pnl_under_real_slippage() -> None:
    """The actual bug: with realistic, direction-dependent execution prices (not an artificial
    equal-price shortcut), a mirrored long and short must still have exactly opposite gross P&L."""
    entry_observed, exit_observed = Decimal(100), Decimal(120)
    notional = Decimal(10_000)

    long_result = _realistic_trade(
        "long", entry_observed=entry_observed, exit_observed=exit_observed, notional=notional
    )
    short_result = _realistic_trade(
        "short", entry_observed=entry_observed, exit_observed=exit_observed, notional=notional
    )
    assert long_result.gross_pnl == -short_result.gross_pnl
    # And matches the spec's explicit formula exactly (quantity from the observed entry price).
    quantity = notional / entry_observed
    assert long_result.gross_pnl == quantity * (exit_observed - entry_observed)
    assert short_result.gross_pnl == quantity * (entry_observed - exit_observed)


def test_profitable_long_mirrors_profitable_short_on_the_opposite_price_move() -> None:
    """A profitable long (price up) and a profitable short (price down by the same amount) on the
    same observed entry price have equal-magnitude gross P&L."""
    entry_observed = Decimal(100)
    long_exit, short_exit = Decimal(120), Decimal(80)

    long_result = _realistic_trade("long", entry_observed=entry_observed, exit_observed=long_exit)
    short_result = _realistic_trade(
        "short", entry_observed=entry_observed, exit_observed=short_exit
    )
    assert long_result.gross_pnl > 0
    assert short_result.gross_pnl > 0
    assert long_result.gross_pnl == short_result.gross_pnl


def test_losing_long_mirrors_losing_short_on_the_opposite_price_move() -> None:
    """A losing long (price down) and a losing short (price up by the same amount) on the same
    observed entry price have equal-magnitude (negative) gross P&L."""
    entry_observed = Decimal(100)
    long_exit, short_exit = Decimal(80), Decimal(120)

    long_result = _realistic_trade("long", entry_observed=entry_observed, exit_observed=long_exit)
    short_result = _realistic_trade(
        "short", entry_observed=entry_observed, exit_observed=short_exit
    )
    assert long_result.gross_pnl < 0
    assert short_result.gross_pnl < 0
    assert long_result.gross_pnl == short_result.gross_pnl


def test_zero_price_movement_produces_zero_gross_pnl_for_both_directions() -> None:
    """No observed price movement at all must yield exactly zero gross P&L, regardless of
    direction or execution-price slippage on either leg."""
    flat_price = Decimal(100)
    for direction in ("long", "short"):
        result = _realistic_trade(direction, entry_observed=flat_price, exit_observed=flat_price)
        assert result.gross_pnl == 0


def test_fee_and_slippage_cost_behavior_is_unchanged_by_the_quantity_fix() -> None:
    """Finding 1 only changes which price sizes ``quantity`` — it must not change the existing,
    already-tested cost model semantics: fees still scale linearly with notional, slippage cost
    stays non-negative, and the net/gross/slippage/fees reconciliation still holds exactly, now
    verified under the same realistic asymmetric-execution-price conditions as the bug itself."""
    entry_observed, exit_observed = Decimal(100), Decimal(110)
    result = _realistic_trade("long", entry_observed=entry_observed, exit_observed=exit_observed)
    assert result.slippage_cost > 0
    assert result.fees_total > 0
    assert result.net_pnl == result.gross_pnl - result.slippage_cost - result.fees_total

    doubled = _realistic_trade(
        "long",
        entry_observed=entry_observed,
        exit_observed=exit_observed,
        notional=Decimal(20_000),
    )
    assert doubled.fees_total == result.fees_total * 2
    assert doubled.quantity == result.quantity * 2


# ------------------------------------------------------------------ fees


def test_fees_scale_with_notional() -> None:
    small = calculate_pnl(
        direction="long",
        notional=Decimal(1_000),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal("100.05"),
        exit_price_observed=Decimal(100),
        exit_price_execution=Decimal("99.95"),
        params=FLAT,
    )
    large = calculate_pnl(
        direction="long",
        notional=Decimal(10_000),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal("100.05"),
        exit_price_observed=Decimal(100),
        exit_price_execution=Decimal("99.95"),
        params=FLAT,
    )
    assert large.fees_total == small.fees_total * 10


def test_zero_fee_params_yield_zero_fees() -> None:
    zero_fee = COST_MODEL_V1.__class__(
        version="test_zero",
        fee_bps=Decimal(0),
        slippage_bps=Decimal(0),
        max_participation_pct=Decimal(5),
        risk_free_rate_annual=Decimal(0),
    )
    result = calculate_pnl(
        direction="long",
        notional=Decimal(10_000),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal(100),
        exit_price_observed=Decimal(110),
        exit_price_execution=Decimal(110),
        params=zero_fee,
    )
    assert result.fees_total == 0
    assert result.slippage_cost == 0
    assert result.net_pnl == result.gross_pnl


# ------------------------------------------------------------------ slippage: v1 vs v2


def test_participation_impact_coefficient_is_inert_without_a_fraction() -> None:
    """``execution_price`` never passes ``participation_fraction`` (Phase 24 spec deviation,
    documented: flat slippage only), so cost_model_v2's non-zero coefficient has no effect — v1
    and v2 execution prices are identical given the same slippage_bps."""
    v1_price = execution_price(Decimal(100), direction="long", leg="entry", params=COST_MODEL_V1)
    v2_price = execution_price(Decimal(100), direction="long", leg="entry", params=COST_MODEL_V2)
    assert v1_price == v2_price


# ------------------------------------------------------------------ leverage


def test_leverage_amplifies_return_pct_not_dollar_pnl() -> None:
    """Spec: "Handle leverage correctly without confusing leveraged exposure with actual P&L."
    Dollar P&L depends only on notional (actual simulated position size); return% (on margin)
    scales inversely with margin, i.e. up with leverage."""
    unleveraged = calculate_pnl(
        direction="long",
        notional=Decimal(10_000),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal(100),
        exit_price_observed=Decimal(110),
        exit_price_execution=Decimal(110),
        params=COST_MODEL_V1,
    )
    leveraged = calculate_pnl(
        direction="long",
        notional=Decimal(10_000),
        leverage=Decimal(10),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal(100),
        exit_price_observed=Decimal(110),
        exit_price_execution=Decimal(110),
        params=COST_MODEL_V1,
    )
    # Same notional -> identical dollar P&L regardless of leverage.
    assert leveraged.net_pnl == unleveraged.net_pnl
    assert leveraged.gross_pnl == unleveraged.gross_pnl
    # But margin is 10x smaller, so return% is 10x larger.
    assert leveraged.margin == unleveraged.margin / 10
    assert leveraged.return_pct == unleveraged.return_pct * 10


def test_zero_leverage_margin_guarded_against_division_by_zero() -> None:
    """``calculate_pnl`` itself never receives a zero/negative leverage (the service validates
    this before calling it), but the function stays defensive: a zero margin yields a defined
    0% return rather than raising."""
    result = calculate_pnl(
        direction="long",
        notional=Decimal(0),
        leverage=Decimal(1),
        entry_price_observed=Decimal(100),
        entry_price_execution=Decimal(100),
        exit_price_observed=Decimal(110),
        exit_price_execution=Decimal(110),
        params=COST_MODEL_V1,
    )
    assert result.return_pct == 0


# -------------------------------------------------------------- max favorable / adverse movement


def test_max_favorable_adverse_long() -> None:
    move = max_favorable_adverse("long", Decimal(100), [Decimal(90), Decimal(105), Decimal(95)])
    assert move.favorable_pct == Decimal(5)  # (105-100)/100 * 100
    assert move.adverse_pct == Decimal(-10)  # (90-100)/100 * 100


def test_max_favorable_adverse_short() -> None:
    move = max_favorable_adverse("short", Decimal(100), [Decimal(90), Decimal(105), Decimal(95)])
    assert move.favorable_pct == Decimal(10)  # price fell to 90, favorable for a short
    assert move.adverse_pct == Decimal(-5)  # price rose to 105, adverse for a short


def test_max_favorable_adverse_empty_path_is_insufficient_data() -> None:
    move = max_favorable_adverse("long", Decimal(100), [])
    assert move.favorable_pct is None
    assert move.adverse_pct is None


def test_max_favorable_adverse_zero_entry_price_is_insufficient_data() -> None:
    move = max_favorable_adverse("long", Decimal(0), [Decimal(10)])
    assert move.favorable_pct is None
    assert move.adverse_pct is None
