"""Retail activity calculated metrics (L2) and historical-percentile statistical signals (L3).

Pure functions (no I/O). Every input is point-in-time data (``available_at <= as_of``) supplied
by the service. Every threshold is a **judgment parameter chosen by design** (not fitted to data)
and is published alongside each result (``PARAMETERS``).

**Measurement class (R1, R5's evidence-class discipline applied to measurement type, not actor
identity): every metric below carries ``measurement_class = "proxy"``.** No input this platform
tracks is retail-exclusive data (see ``retail/universe.py``'s module docstring for why); nothing
here is ever labelled ``"direct"``. The field exists, and is checked by tests, so that if a future
phase adds a genuinely retail-segmented source (e.g. a broker's own retail-flow disclosure), it is
structurally impossible to present it identically to today's proxies.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

DAY = timedelta(days=1)
WEEK = timedelta(days=7)

MeasurementClass = str  # "proxy" (only value used in Phase 10 — see module docstring)
PROXY: MeasurementClass = "proxy"

# A "latest" derivatives reading must be at most this old (Binance funding/ratio data is hourly).
DERIVATIVES_LATEST_TOLERANCE = timedelta(hours=6)
# A trending-coin snapshot must be at most this old (polled every 3 h — see retail/sources.py).
TRENDING_LATEST_TOLERANCE = timedelta(hours=8)
# A small-output-count day must be at most this old (daily aggregation, some settle delay).
SMALL_TX_LATEST_TOLERANCE = timedelta(days=3)

FUNDING_RATE_NEUTRAL = Decimal("0.0001")  # ±0.01% per funding interval counts as biased
ACCOUNT_RATIO_NEUTRAL = Decimal("0.1")  # ±10% away from 1.0 counts as skewed

PARAMETERS: dict[str, str] = {
    "derivatives_latest_tolerance": "a funding-rate / account-ratio reading must be at most 6 h "
    "old to count as 'latest'",
    "trending_latest_tolerance": "a trending-coin snapshot must be at most 8 h old",
    "small_tx_latest_tolerance": "a small-output-count day must be at most 3 days old",
    "funding_rate_neutral": "funding rate within ±0.01% per interval counts as neutral",
    "account_ratio_neutral": "long/short account ratio within ±10% of 1.0 counts as balanced",
}


@dataclass(frozen=True, slots=True)
class Point:
    time: datetime
    value: Decimal | None
    quality_status: str = "ok"

    @property
    def has_value(self) -> bool:
        return self.value is not None


def latest(points: Sequence[Point], as_of: datetime, tolerance: timedelta) -> Point | None:
    usable = [p for p in points if p.has_value and as_of - tolerance <= p.time <= as_of]
    return max(usable, key=lambda p: p.time) if usable else None


class LatestIndex:
    """``latest`` for one series, answerable many times without rescanning it.

    The series is filtered to points that carry a value and stably sorted by time once; each
    lookup is then a binary search. ``at(as_of, tolerance)`` returns exactly what
    ``latest(points, as_of, tolerance)`` returns for the same inputs, including which point wins
    when several share the newest time (the first of them in the original order, as ``max`` does).
    """

    __slots__ = ("_points", "_times", "lookups")

    def __init__(self, points: Sequence[Point]) -> None:
        self._points = sorted((p for p in points if p.has_value), key=lambda p: p.time)
        self._times = [p.time for p in self._points]
        self.lookups = 0

    def at(self, as_of: datetime, tolerance: timedelta) -> Point | None:
        self.lookups += 1
        end = bisect_right(self._times, as_of)
        if end == 0:
            return None
        newest = self._times[end - 1]
        if newest < as_of - tolerance:
            return None
        return self._points[bisect_left(self._times, newest, 0, end)]


# --------------------------------------------------------------------------- historical percentile


@dataclass(frozen=True, slots=True)
class PercentileResult:
    """L3 Statistical Signal: where the current value sits in its own recent history.

    Method: nearest-rank percentile — the percentage of historical points strictly less than the
    current value, plus half the points equal to it (a standard, simple, tie-tolerant definition),
    scaled to 0-100. This is a statistical description of the *platform's own recorded history*,
    not a claim about the true long-run distribution (a short or gappy history is stated as such
    via ``sample_size``, never hidden).
    """

    status: str  # ok / insufficient_history
    reason: str | None = None
    value: Decimal | None = None
    percentile: Decimal | None = None  # 0-100
    sample_size: int = 0


MIN_PERCENTILE_SAMPLE = 20


def percentile_rank(
    history: Sequence[Decimal], current: Decimal, *, min_sample: int = MIN_PERCENTILE_SAMPLE
) -> PercentileResult:
    """Where ``current`` ranks among ``history`` (history should exclude ``current`` itself)."""
    sample = list(history)
    if len(sample) < min_sample:
        return PercentileResult(
            "insufficient_history",
            f"only {len(sample)} historical points available (need >= {min_sample})",
            value=current,
            sample_size=len(sample),
        )
    below = sum(1 for h in sample if h < current)
    equal = sum(1 for h in sample if h == current)
    pct = (Decimal(below) + Decimal(equal) / 2) / Decimal(len(sample)) * 100
    return PercentileResult(
        "ok", value=current, percentile=pct.quantize(Decimal("0.1")), sample_size=len(sample)
    )


# --------------------------------------------------------------------------- derivatives proxy


@dataclass(slots=True)
class DerivativesProxy:
    """Retail-associated derivatives positioning (RETAIL PROXY — see module docstring)."""

    measurement_class: MeasurementClass = field(default=PROXY, init=False)
    status: str = "unavailable"  # ok / unavailable
    reason: str | None = None
    assets_used: tuple[str, ...] = ()
    funding_rate_avg: Decimal | None = None
    account_ratio_avg: Decimal | None = None
    funding_condition: str = "unknown"  # long_biased / short_biased / neutral / unknown
    ratio_condition: str = "unknown"  # long_skewed / short_skewed / balanced / unknown


def _avg(values: Sequence[Decimal]) -> Decimal | None:
    return None if not values else sum(values, Decimal(0)) / len(values)


def derivatives_proxy(
    funding_by_asset: Mapping[str, Sequence[Point]],
    ratio_by_asset: Mapping[str, Sequence[Point]],
    as_of: datetime,
) -> DerivativesProxy:
    """Average, across every tracked perp with a fresh reading, of Binance's funding rate and
    "global" (all-account) long/short account ratio — both proxies, never retail-exclusive data
    (see module and ``retail/universe.py`` docstrings)."""
    return _derivatives_proxy(
        sorted(set(funding_by_asset) | set(ratio_by_asset)),
        lambda asset: latest(funding_by_asset.get(asset, ()), as_of, DERIVATIVES_LATEST_TOLERANCE),
        lambda asset: latest(ratio_by_asset.get(asset, ()), as_of, DERIVATIVES_LATEST_TOLERANCE),
        as_of,
    )


class DerivativesProxySeries:
    """``derivatives_proxy`` evaluated at many ``as_of`` times over the same input series.

    Indexes every series once (``LatestIndex``) so each evaluation costs a few binary searches
    instead of a full scan of every series. ``at(t)`` equals
    ``derivatives_proxy(funding_by_asset, ratio_by_asset, t)`` for every ``t``."""

    def __init__(
        self,
        funding_by_asset: Mapping[str, Sequence[Point]],
        ratio_by_asset: Mapping[str, Sequence[Point]],
    ) -> None:
        self._assets = sorted(set(funding_by_asset) | set(ratio_by_asset))
        self._funding = {a: LatestIndex(funding_by_asset.get(a, ())) for a in self._assets}
        self._ratio = {a: LatestIndex(ratio_by_asset.get(a, ())) for a in self._assets}

    def at(self, as_of: datetime) -> DerivativesProxy:
        return _derivatives_proxy(
            self._assets,
            lambda asset: self._funding[asset].at(as_of, DERIVATIVES_LATEST_TOLERANCE),
            lambda asset: self._ratio[asset].at(as_of, DERIVATIVES_LATEST_TOLERANCE),
            as_of,
        )


def _derivatives_proxy(
    assets: Sequence[str],
    funding_latest: Callable[[str], Point | None],
    ratio_latest: Callable[[str], Point | None],
    as_of: datetime,
) -> DerivativesProxy:
    funding_values: list[Decimal] = []
    ratio_values: list[Decimal] = []
    assets_used: list[str] = []
    for asset in assets:
        f = funding_latest(asset)
        r = ratio_latest(asset)
        used = False
        if f is not None and f.value is not None:
            funding_values.append(f.value)
            used = True
        if r is not None and r.value is not None:
            ratio_values.append(r.value)
            used = True
        if used:
            assets_used.append(asset)
    if not funding_values and not ratio_values:
        return DerivativesProxy(
            status="unavailable",
            reason=f"no funding-rate or account-ratio reading within "
            f"{DERIVATIVES_LATEST_TOLERANCE} of {as_of.isoformat()} for any tracked perp",
        )
    funding_avg = _avg(funding_values)
    ratio_avg = _avg(ratio_values)
    funding_condition = "unknown"
    if funding_avg is not None:
        funding_condition = (
            "long_biased"
            if funding_avg >= FUNDING_RATE_NEUTRAL
            else "short_biased"
            if funding_avg <= -FUNDING_RATE_NEUTRAL
            else "neutral"
        )
    ratio_condition = "unknown"
    if ratio_avg is not None:
        deviation = ratio_avg - 1
        ratio_condition = (
            "long_skewed"
            if deviation >= ACCOUNT_RATIO_NEUTRAL
            else "short_skewed"
            if deviation <= -ACCOUNT_RATIO_NEUTRAL
            else "balanced"
        )
    return DerivativesProxy(
        status="ok",
        assets_used=tuple(assets_used),
        funding_rate_avg=funding_avg,
        account_ratio_avg=ratio_avg,
        funding_condition=funding_condition,
        ratio_condition=ratio_condition,
    )


# --------------------------------------------------------------------------- trending / meme-coin


@dataclass(frozen=True, slots=True)
class TrendingSnapshot:
    """One poll's stored trending coins: asset symbol -> rank (0 = most trending)."""

    time: datetime
    ranks: dict[str, int]


@dataclass(slots=True)
class MemeCoinActivity:
    """RETAIL PROXY: presence and rank of a curated, non-exhaustive meme-coin list within
    CoinGecko's trending-by-search list (see ``retail/universe.py::MEME_COIN_SYMBOLS``)."""

    measurement_class: MeasurementClass = field(default=PROXY, init=False)
    status: str = "unavailable"
    reason: str | None = None
    as_of_snapshot: datetime | None = None
    trending_meme_coins: tuple[str, ...] = ()
    best_rank: dict[str, int] = field(default_factory=dict)
    meme_coins_trending_count: int = 0


def meme_coin_activity(
    latest_snapshot: TrendingSnapshot | None, meme_symbols: Sequence[str]
) -> MemeCoinActivity:
    if latest_snapshot is None:
        return MemeCoinActivity(
            status="unavailable", reason="no trending-coin snapshot within tolerance"
        )
    tracked = {sym: rank for sym, rank in latest_snapshot.ranks.items() if sym in meme_symbols}
    return MemeCoinActivity(
        status="ok",
        as_of_snapshot=latest_snapshot.time,
        trending_meme_coins=tuple(sorted(tracked)),
        best_rank=dict(tracked),
        meme_coins_trending_count=len(tracked),
    )


# --------------------------------------------------------------------------- small transactions


@dataclass(slots=True)
class SmallTransactionActivity:
    """RETAIL PROXY: count of small-value Bitcoin outputs. **Not filtered** for change outputs
    from large transactions, exchange-internal batching, or dust — a noisy proxy, stated plainly.
    """

    measurement_class: MeasurementClass = field(default=PROXY, init=False)
    status: str = "unavailable"
    reason: str | None = None
    latest_count: Point | None = None
    week_avg: Decimal | None = None
    change_vs_week_avg: Decimal | None = None  # (latest - week_avg) / week_avg


def small_transaction_activity(
    points: Sequence[Point], as_of: datetime
) -> SmallTransactionActivity:
    now = latest(points, as_of, SMALL_TX_LATEST_TOLERANCE)
    if now is None or now.value is None:
        return SmallTransactionActivity(
            status="unavailable",
            reason=f"no small-output-count day within {SMALL_TX_LATEST_TOLERANCE} of "
            f"{as_of.isoformat()}",
        )
    window_start = now.time - WEEK
    trailing = [
        p.value for p in points if p.has_value and window_start <= p.time < now.time and p.value
    ]
    week_avg = _avg(trailing)
    change = None
    if week_avg is not None and week_avg > 0:
        change = (now.value - week_avg) / week_avg
    return SmallTransactionActivity(
        status="ok", latest_count=now, week_avg=week_avg, change_vs_week_avg=change
    )


def trailing_values(points: Sequence[Point], as_of: datetime, span: timedelta) -> list[Decimal]:
    """Values in (as_of - span, as_of) — the population a percentile is computed against."""
    start = as_of - span
    return [
        p.value for p in points if p.has_value and start <= p.time < as_of and p.value is not None
    ]
