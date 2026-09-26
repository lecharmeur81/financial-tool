"""Derivatives datasets (Phase 8).

What is tracked and where it comes from (all public endpoints, no keys):

- **open interest** of USDT-margined perpetuals (BTC, ETH, SOL, XRP), hourly snapshots, in coins —
  Binance USDⓈ-M and OKX;
- **funding rates** of the same perpetuals, one value per funding settlement — Binance and OKX;
- **long/short account ratio**, hourly — Binance (all accounts on the perpetual) and OKX (all
  accounts holding the coin's contracts). The two venues count different populations, so they are
  never combined;
- **liquidations** of OKX USDT perpetuals, hourly totals in coins for long and short positions,
  aggregated from OKX's public liquidation orders (Binance offers no REST history);
- **futures curve** (dated futures and the perpetual: mark, index, open interest, volume) and the
  **option chain** (mark price, mark implied volatility, open interest, 24 h volume per option) of
  Deribit, BTC and ETH, as venue snapshots;
- **implied volatility index** (Deribit DVOL, 30-day expected volatility), BTC and ETH, hourly.

USD amounts are *not* stored for open interest or liquidations: venues report them in USDT or in
different conventions. They are calculated at read time from coins × the Coinbase USD price
(ADR-0050). Percentages reported by venues (implied volatility, DVOL) are stored as ratios
(0.45 = 45 %), with the conversion recorded in ``transformations``.

Not available from free sources (``NOT_TRACKED``): Binance liquidation history, options on SOL and
XRP, top-trader positioning, exchange-wide aggregates of every venue.

``event_time`` conventions: hourly snapshots (open interest, account ratios) use the snapshot
time on the hour; funding uses the settlement time; hourly totals (liquidations) and the DVOL
candle use the start of the hour they cover; Deribit snapshots use Deribit's response time.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Literal

from cfi.domain.datasets import AvailabilityRule, DatasetSpec

PERP_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")
OPTION_ASSETS: tuple[str, ...] = ("BTC", "ETH")  # Deribit futures, options and DVOL
HOUR = timedelta(hours=1)

Metric = Literal[
    "open_interest",
    "funding_rate",
    "long_short_account_ratio",
    "liquidations",
    "volatility_index",
    "futures_curve",
    "option_chain",
]

# Snapshots are published within minutes; one received earlier is dated by receipt.
_SNAPSHOT = AvailabilityRule("event_time_plus", timedelta(minutes=5), known_when_received=True)
_SETTLEMENT = AvailabilityRule("event_time_plus", timedelta(minutes=1), known_when_received=True)
_HOUR_CLOSED = AvailabilityRule("period_end_plus", timedelta(minutes=2))
_RESPONSE_TIME = AvailabilityRule("provider")

NOT_TRACKED: tuple[dict[str, str], ...] = (
    {
        "item": "Binance liquidations",
        "reason": "Binance publishes liquidations only as a live stream (no REST history); only "
        "OKX liquidations are counted, so totals are one venue's, not the market's.",
    },
    {
        "item": "Options, futures basis and DVOL for SOL and XRP",
        "reason": "Deribit lists no inverse futures or options on them in the free public data "
        "used here.",
    },
    {
        "item": "Top-trader long/short positioning",
        "reason": "Venue definitions of 'top trader' differ and are not published in detail; only "
        "all-account ratios are shown.",
    },
    {
        "item": "Market-wide totals",
        "reason": "Open interest and funding cover Binance and OKX only (plus Deribit for the "
        "curve and options); other venues are not included.",
    },
)


def perp_ref(asset: str) -> str:
    """The USDT-margined perpetual of ``asset`` (the venue is carried separately)."""
    return f"PERP:{asset}-USDT"


def contracts_ref(asset: str) -> str:
    """All of a venue's contracts on ``asset`` (OKX account ratio population)."""
    return f"CONTRACTS:{asset}"


def liquidation_ref(asset: str, side: Literal["long", "short"]) -> str:
    return f"{perp_ref(asset)}:{side}"


def deribit_ref(instrument: str) -> str:
    return f"DERIBIT:{instrument}"


def dvol_ref(asset: str) -> str:
    return f"DVOL:{asset}"


def _hourly(
    dataset_id: str, metric: str, unit: str, availability: AvailabilityRule, description: str
) -> DatasetSpec:
    return DatasetSpec(
        dataset_id=dataset_id,
        metric=metric,
        unit=unit,
        period="1h",
        availability=availability,
        freshness_limit=timedelta(hours=3),
        conflict_tolerance=Decimal("0.01"),
        revisable=True,
        expect_continuous=True,
        description=description,
    )


FUNDING_RATE = DatasetSpec(
    dataset_id="deriv.funding_rate",
    metric="funding_rate",
    unit="ratio",
    period="event",
    availability=_SETTLEMENT,
    freshness_limit=timedelta(hours=12),
    conflict_tolerance=Decimal("0.0001"),
    revisable=True,
    description=(
        "Funding rate settled on a perpetual at event_time, as a ratio per funding interval "
        "(0.0001 = 0.01 %). Positive: long positions pay short positions. Intervals differ by "
        "venue and instrument (usually 8 h)."
    ),
)

LONG_SHORT_RATIO = _hourly(
    "deriv.long_short_account_ratio.1h",
    "long_short_account_ratio",
    "ratio",
    _SNAPSHOT,
    "Accounts with net long positions ÷ accounts with net short positions, hourly snapshot. "
    "Binance: all accounts on the USDT perpetual; OKX: all accounts holding the coin's contracts. "
    "Different populations: never combined across venues. Context only — counts accounts, not "
    "position sizes.",
)

VOLATILITY_INDEX = _hourly(
    "deriv.volatility_index.1h",
    "volatility_index",
    "ratio",
    _HOUR_CLOSED,
    "Deribit DVOL: expected annualised volatility over the next 30 days implied by the option "
    "chain, closing value of the hour (event_time = start of the hour). Stored as a ratio "
    "(0.45 = 45 %).",
)


def _per_asset() -> dict[tuple[str, str], DatasetSpec]:
    out: dict[tuple[str, str], DatasetSpec] = {}
    for asset in PERP_ASSETS:
        a = asset.lower()
        out[("open_interest", asset)] = _hourly(
            f"deriv.open_interest.{a}.1h",
            "open_interest",
            a,
            _SNAPSHOT,
            f"Open interest of the {asset}-USDT perpetual in {asset}, hourly snapshot "
            "(event_time = snapshot time, on the hour).",
        )
        out[("funding_rate", asset)] = FUNDING_RATE
        out[("long_short_account_ratio", asset)] = LONG_SHORT_RATIO
        out[("liquidations", asset)] = _hourly(
            f"deriv.liquidations.{a}.1h",
            "liquidations",
            a,
            _HOUR_CLOSED,
            f"{asset} of long (subject …:long) and short (…:short) positions liquidated on the "
            f"OKX {asset}-USDT perpetual during the hour (contracts × contract value). A zero "
            "means no liquidation orders were published for the hour; hours whose orders could "
            "not all be read are stored as missing.",
        )
    for asset in OPTION_ASSETS:
        a = asset.lower()
        out[("volatility_index", asset)] = VOLATILITY_INDEX
        out[("futures_curve", asset)] = DatasetSpec(
            dataset_id=f"deriv.futures_curve.{a}",
            metric="futures_curve",
            unit="usd",
            period="event",
            availability=_RESPONSE_TIME,
            freshness_limit=timedelta(hours=3),
            conflict_tolerance=Decimal("0.01"),
            kind="quote",
            description=(
                f"Deribit {asset} dated futures and perpetual (inverse, USD-quoted): mark, bid, "
                "ask, index price, open interest (USD) and 24 h volume, one row per instrument "
                "per snapshot (event_time = Deribit's response time)."
            ),
        )
        out[("option_chain", asset)] = DatasetSpec(
            dataset_id=f"deriv.option_chain.{a}",
            metric="option_chain",
            unit=a,
            period="event",
            availability=_RESPONSE_TIME,
            freshness_limit=timedelta(hours=9),
            conflict_tolerance=Decimal("0.05"),
            kind="quote",
            description=(
                f"Deribit {asset} options: mark price (in {asset}), bid, ask, mark implied "
                f"volatility (ratio), forward and index price (USD), open interest and 24 h "
                f"volume ({asset}; one contract = 1 {asset}), one row per option per snapshot "
                "(event_time = Deribit's response time)."
            ),
        )
    return out


DATASETS: dict[tuple[str, str], DatasetSpec] = _per_asset()


def dataset(metric: str, asset: str) -> DatasetSpec:
    try:
        return DATASETS[(metric, asset)]
    except KeyError:
        raise KeyError(f"no derivatives dataset {metric!r} for {asset}") from None


def has_dataset(metric: str, asset: str) -> bool:
    return (metric, asset) in DATASETS


def all_datasets() -> list[DatasetSpec]:
    unique: dict[str, DatasetSpec] = {}
    for spec in DATASETS.values():
        unique.setdefault(spec.dataset_id, spec)
    return list(unique.values())


def dataset_by_id(dataset_id: str) -> DatasetSpec:
    for spec in DATASETS.values():
        if spec.dataset_id == dataset_id:
            return spec
    raise KeyError(dataset_id)


def metric_of(dataset_id: str) -> str:
    return dataset_by_id(dataset_id).metric
