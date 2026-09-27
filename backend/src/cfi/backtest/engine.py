"""The historical-replay backtest loop (Phase 16).

Event-driven, one simulated day at a time, in this fixed order per day ``i`` (bars indexed oldest
first):

1. **Execute** any order scheduled on the PRIOR day, at TODAY's open (``bars[i].open``) — this is
   the deliberate execution lag (see ``cfi.backtest`` module docstring): a signal computed from
   yesterday's close can only be acted on today, never at the instant it was computed.
2. **Check stops** — if currently in a position, a stop-loss/take-profit may trigger intrabar
   against TODAY's own high/low, executing immediately (the one exception to the execution lag:
   stops are risk controls, not signal decisions) at the stop/take-profit level — slipped like any
   other fill, and at TODAY's own (slipped) open instead when the open already gapped through the
   level, since that is the worst price a real order could have achieved that day (ADR-0061,
   RED_TEAM_REPORT.md finding #3).
3. **Mark to market** at TODAY's close, recording one ``EquityPoint``.
4. **Decide** tomorrow's order — the signal is computed from ``bars[: i + 1]`` only (never a later
   index) and, for a domain-score signal, gathered with ``as_of = knowledge_time = bars[i].time``
   (never this run's own, later, global ``as_of``) — the structural anti-look-ahead discipline this
   phase requires.

No parameter search happens anywhere in this loop — it evaluates exactly the one
``StrategyDefinition`` it is given, once, over the requested window.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from cfi.backtest import costs as cost_module
from cfi.backtest.metrics import BacktestMetrics, EquityPoint, Trade, compute_metrics
from cfi.backtest.signals import SignalReading
from cfi.backtest.strategy import StopConditions, StrategyDefinition, compare
from cfi.backtest.universe import LIQUIDITY_LOOKBACK_DAYS, WARMUP_DAYS
from cfi.backtest.versioning import Assumptions, RunVersions, code_version, dataset_version
from cfi.core.time import utc_now
from cfi.divergence.adapters import Adapters
from cfi.market.sources import VENUES
from cfi.market.universe import ohlcv_dataset_id
from cfi.market_structure.metrics import Bar, bars_from_rows, realized_volatility

_VENUE = VENUES["coinbase"]
_OHLCV_DATASET_ID = ohlcv_dataset_id(_VENUE.quote, "1d")


@dataclass(slots=True)
class _Position:
    entry_date: datetime
    entry_price: Decimal
    size_base: Decimal
    notional_at_entry: Decimal
    entry_fee: Decimal
    last_mark_price: Decimal


@dataclass(slots=True)
class _PendingOrder:
    kind: str  # "entry" | "exit"
    size_base: Decimal | None = None  # only for "entry"
    reason: str = ""  # only for "exit": "signal_exit" | "time_exit"


@dataclass(frozen=True, slots=True)
class BacktestResult:
    status: str  # "ok" | "insufficient_data"
    reason: str | None
    versions: RunVersions
    assumptions: Assumptions
    metrics: BacktestMetrics | None
    trades: tuple[Trade, ...]
    equity_curve: tuple[EquityPoint, ...]
    warnings: tuple[str, ...] = field(default_factory=tuple)


async def _fetch_bars(
    adapters: Adapters, *, asset: str, start: datetime, end: datetime, as_of: datetime
) -> list[Bar]:
    queries = adapters.market()
    instrument = _VENUE.instruments.get(asset)
    if instrument is None:
        return []
    series_id = await queries.series_id(_OHLCV_DATASET_ID, instrument)
    if series_id is None:
        return []
    rows = await queries.bars(
        series_id, _VENUE.provider_id, start - timedelta(days=WARMUP_DAYS), end, as_of
    )
    return bars_from_rows(rows)


def _warmup_shortfall_warning(bars: list[Bar], start_idx: int) -> str | None:
    """RED_TEAM_REPORT.md finding #14: fewer than ``WARMUP_DAYS`` bars available before
    ``start_idx`` means a long-lookback signal (e.g. SMA200) silently evaluates over less history
    than the strategy assumes. Mirrors the existing liquidity-cap warning convention — surfaced,
    never silent (R3)."""
    available = start_idx
    if available < WARMUP_DAYS:
        return (
            f"only {available} bar(s) of warmup history are available before the requested "
            f"start date (wanted {WARMUP_DAYS}); long-lookback signals (e.g. SMA200) may be "
            f"computed over fewer bars than assumed for the earliest decisions in this run"
        )
    return None


async def _signal_value(
    strategy: StrategyDefinition, bars_through_today: list[Bar], adapters: Adapters
) -> SignalReading:
    return await strategy.signal.value_at(
        bars_through_today, adapters, as_of=bars_through_today[-1].time
    )


def _trailing_avg_volume(bars_through_today: list[Bar]) -> Decimal | None:
    window = bars_through_today[-LIQUIDITY_LOOKBACK_DAYS:]
    volumes = [b.volume for b in window if b.volume is not None]
    if len(volumes) < LIQUIDITY_LOOKBACK_DAYS:
        return None
    return sum(volumes, Decimal(0)) / len(volumes)


def _participation_fraction(
    notional: Decimal,
    bars_through_today: list[Bar],
    price: Decimal,
    params: cost_module.CostParameterSet,
) -> Decimal | None:
    """This fill's notional as a fraction of the day's liquidity cap (finding #5) — ``None`` when
    the cap itself can't be computed (missing trailing volume), in which case ``slipped_price``
    falls back to its flat-bps behavior rather than blocking the fill."""
    trailing_volume = _trailing_avg_volume(bars_through_today)
    cap = cost_module.liquidity_cap(trailing_volume, price, params)
    if cap is None or cap <= 0:
        return None
    return notional / cap


def _intrabar_stop_fill(
    position: _Position, today: Bar, stops: StopConditions
) -> tuple[str, Decimal] | None:
    """Whether a stop-loss/take-profit fires on ``today`` and the RAW (pre-slippage) fill price
    for it (finding #3).

    Checks the day's own OPEN first: if the market already gapped through the stop/take-profit
    level before the bar even began, that gapped-through open — not the theoretical stop level —
    is the worst (for stop-loss) or the actual (for take-profit) price a real order could have
    achieved that day. Only when the open has NOT already passed the level does the classic
    intrabar low/high check against the exact stop level apply. The caller still applies slippage
    on top of whichever raw price this returns — this function only ever returns unslipped,
    theoretical prices.
    """
    if stops.stop_loss_pct is not None:
        sl = position.entry_price * (1 - stops.stop_loss_pct / 100)
        if today.open <= sl:
            return "stop_loss", today.open
        if today.low <= sl:
            return "stop_loss", sl
    if stops.take_profit_pct is not None:
        tp = position.entry_price * (1 + stops.take_profit_pct / 100)
        if today.open >= tp:
            return "take_profit", today.open
        if today.high >= tp:
            return "take_profit", tp
    return None


def _sized_notional(
    strategy: StrategyDefinition,
    *,
    equity: Decimal,
    bars_through_today: list[Bar],
    price: Decimal,
    cost_params: cost_module.CostParameterSet,
    warnings: list[str],
    today: datetime,
) -> Decimal:
    sizing = strategy.position_sizing
    if sizing.method == "fixed_fraction":
        desired = equity * sizing.value
    elif sizing.method == "fixed_notional":
        desired = sizing.value
    else:  # "volatility_target"
        vol = realized_volatility(bars_through_today)
        if vol.status != "ok" or vol.annualized_pct is None or vol.annualized_pct == 0:
            warnings.append(f"{today.date().isoformat()}: volatility_target sizing unavailable")
            return Decimal(0)
        desired = equity * (sizing.value / vol.annualized_pct)

    max_by_leverage = equity * strategy.risk_limits.max_leverage
    max_by_exposure = equity * strategy.risk_limits.max_exposure_pct / 100
    capped = min(desired, max_by_leverage, max_by_exposure)

    trailing_volume = _trailing_avg_volume(bars_through_today)
    cap = cost_module.liquidity_cap(trailing_volume, price, cost_params)
    if cap is None:
        warnings.append(
            f"{today.date().isoformat()}: liquidity cap unavailable (insufficient trailing volume)"
        )
        return max(Decimal(0), capped)
    return max(Decimal(0), min(capped, cap))


async def run_backtest(
    *,
    adapters: Adapters,
    strategy: StrategyDefinition,
    asset: str,
    start: datetime,
    end: datetime,
    as_of: datetime,
    initial_capital: Decimal,
    cost_params: cost_module.CostParameterSet | None = None,
) -> BacktestResult:
    params = cost_params or cost_module.parameters()
    created_at = utc_now()
    assumptions = Assumptions(
        asset=asset,
        start=start,
        end=end,
        as_of=as_of,
        knowledge_time=as_of,
        initial_capital=initial_capital,
        fee_bps=params.fee_bps,
        slippage_bps=params.slippage_bps,
        max_participation_pct=params.max_participation_pct,
        risk_free_rate_annual=params.risk_free_rate_annual,
    )
    versions = RunVersions(
        strategy_id=strategy.strategy_id,
        strategy_version=strategy.version,
        parameter_version=params.version,
        dataset_version=dataset_version(
            asset=asset,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=as_of,
            provider_id=_VENUE.provider_id,
        ),
        code_version=code_version(),
        created_at=created_at,
    )

    bars = await _fetch_bars(adapters, asset=asset, start=start, end=end, as_of=as_of)
    start_idx = next((i for i, b in enumerate(bars) if b.time >= start), None)
    if start_idx is None or len(bars) - start_idx < 2:
        return BacktestResult(
            status="insufficient_data",
            reason="fewer than 2 usable bars in the requested window",
            versions=versions,
            assumptions=assumptions,
            metrics=None,
            trades=(),
            equity_curve=(),
        )

    equity = initial_capital
    position: _Position | None = None
    pending: _PendingOrder | None = None
    trades: list[Trade] = []
    equity_curve: list[EquityPoint] = []
    warnings: list[str] = []
    warmup_warning = _warmup_shortfall_warning(bars, start_idx)
    if warmup_warning is not None:
        warnings.append(warmup_warning)

    last_idx = len(bars) - 2  # need bars[i + 1] to execute an order decided on day i
    for i in range(start_idx, last_idx + 1):
        today = bars[i]
        bars_through_today = bars[: i + 1]

        # 1. Execute any order scheduled yesterday, at today's open.
        if pending is not None and pending.kind == "entry" and position is None:
            size_base = pending.size_base or Decimal(0)
            frac = _participation_fraction(
                size_base * today.open, bars_through_today, today.open, params
            )
            entry_price = cost_module.slipped_price(
                today.open, direction="buy", params=params, participation_fraction=frac
            )
            notional = size_base * entry_price
            fee = cost_module.apply_fee(notional, params)
            equity -= fee
            position = _Position(
                entry_date=today.time,
                entry_price=entry_price,
                size_base=size_base,
                notional_at_entry=notional,
                entry_fee=fee,
                last_mark_price=entry_price,
            )
        elif pending is not None and pending.kind == "exit" and position is not None:
            frac = _participation_fraction(
                position.size_base * today.open, bars_through_today, today.open, params
            )
            exit_price = cost_module.slipped_price(
                today.open, direction="sell", params=params, participation_fraction=frac
            )
            equity += position.size_base * (exit_price - position.last_mark_price)
            fee = cost_module.apply_fee(position.size_base * exit_price, params)
            equity -= fee
            trades.append(_close_trade(position, exit_price, fee, pending.reason, today.time))
            position = None
        pending = None

        # 2. Intrabar stop check (executes immediately, no lag — but slipped, and fills at the
        # day's own open when it already gapped through the level: finding #3).
        if position is not None:
            fill = _intrabar_stop_fill(position, today, strategy.stops)
            if fill is not None:
                reason, raw_price = fill
                frac = _participation_fraction(
                    position.size_base * raw_price, bars_through_today, raw_price, params
                )
                stop_price = cost_module.slipped_price(
                    raw_price, direction="sell", params=params, participation_fraction=frac
                )
                equity += position.size_base * (stop_price - position.last_mark_price)
                fee = cost_module.apply_fee(position.size_base * stop_price, params)
                equity -= fee
                trades.append(_close_trade(position, stop_price, fee, reason, today.time))
                position = None

        # 3. Mark to market at today's close (only if still in position after any stop above).
        if position is not None:
            equity += position.size_base * (today.close - position.last_mark_price)
            position.last_mark_price = today.close
        exposure_pct = (
            (position.size_base * today.close / equity * 100)
            if position is not None and equity > 0
            else Decimal(0)
        )
        equity_curve.append(EquityPoint(date=today.time, equity=equity, exposure_pct=exposure_pct))

        # 4. Decide tomorrow's order from data through today only.
        reading = await _signal_value(strategy, bars_through_today, adapters)
        if position is not None:
            holding_days = (today.time - position.entry_date).days
            time_exit_due = (
                strategy.time_exit.max_holding_days is not None
                and holding_days >= strategy.time_exit.max_holding_days
            )
            signal_exit_due = False
            if reading.status == "ok" and reading.value is not None:
                signal_exit_due = compare(
                    reading.value, strategy.exit_comparator, strategy.exit_threshold
                )
            if time_exit_due or signal_exit_due:
                exit_reason = "time_exit" if time_exit_due else "signal_exit"
                pending = _PendingOrder(kind="exit", reason=exit_reason)
        else:
            entry_due = False
            if reading.status == "ok" and reading.value is not None:
                entry_due = compare(
                    reading.value, strategy.entry_comparator, strategy.entry_threshold
                )
            if entry_due:
                notional = _sized_notional(
                    strategy,
                    equity=equity,
                    bars_through_today=bars_through_today,
                    price=today.close,
                    cost_params=params,
                    warnings=warnings,
                    today=today.time,
                )
                if notional > 0:
                    pending = _PendingOrder(kind="entry", size_base=notional / today.close)

    # Force-close any still-open position at the final available bar, for reporting purposes.
    if position is not None:
        final = bars[last_idx + 1]
        bars_through_final = bars[: last_idx + 2]
        frac = _participation_fraction(
            position.size_base * final.close, bars_through_final, final.close, params
        )
        exit_price = cost_module.slipped_price(
            final.close, direction="sell", params=params, participation_fraction=frac
        )
        equity += position.size_base * (exit_price - position.last_mark_price)
        fee = cost_module.apply_fee(position.size_base * exit_price, params)
        equity -= fee
        trades.append(_close_trade(position, exit_price, fee, "end_of_backtest", final.time))
        equity_curve.append(EquityPoint(date=final.time, equity=equity, exposure_pct=Decimal(0)))

    metrics = compute_metrics(
        equity_curve=equity_curve, trades=trades, risk_free_rate_annual=params.risk_free_rate_annual
    )
    return BacktestResult(
        status="ok",
        reason=None,
        versions=versions,
        assumptions=assumptions,
        metrics=metrics,
        trades=tuple(trades),
        equity_curve=tuple(equity_curve),
        warnings=tuple(warnings),
    )


def _close_trade(
    position: _Position, exit_price: Decimal, exit_fee: Decimal, reason: str, exit_date: datetime
) -> Trade:
    pnl = (exit_price - position.entry_price) * position.size_base - position.entry_fee - exit_fee
    return_pct = (
        (pnl / position.notional_at_entry * 100) if position.notional_at_entry > 0 else Decimal(0)
    )
    return Trade(
        entry_date=position.entry_date,
        exit_date=exit_date,
        entry_price=position.entry_price,
        exit_price=exit_price,
        size_base=position.size_base,
        notional_at_entry=position.notional_at_entry,
        fees_paid=position.entry_fee + exit_fee,
        pnl=pnl,
        return_pct=return_pct,
        exit_reason=reason,
    )
