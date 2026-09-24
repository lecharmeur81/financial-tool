"""Institutional capital datasets (Phase 6).

What is tracked, and why each is (or is not) "institutional" (R5, ARCHITECTURE §6):

- US spot ETF flows, aggregate — all US spot ETFs of an asset — **direct**: creations and
  redemptions of regulated funds;
- US spot ETF flows, per fund — one ETF — **direct**: the same, per fund / issuer;
- BTC treasury purchases — one listed company — **attributed**: acquisitions the company
  disclosed, as compiled by the provider;
- Listed-company holdings — all listed companies the provider tracks — **attributed**: holdings
  the companies disclosed, as compiled by the provider.

ETF flows are direct evidence of flows through a regulated fund — not of who bought the fund
shares (end investors include retail). No wallet is ever labelled institutional here.

``event_time`` conventions:
- ETF rows: the US trading date, stored as a 00:00 UTC label (the session itself runs 09:30-16:00
  New York time). Flows settle T+1 at the provider; availability follows the dataset rule.
- Treasury purchases: the date the provider gives for the purchase, as a 00:00 UTC label.
- Holdings snapshots: the time the snapshot was received.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from cfi.domain.datasets import AvailabilityRule, DatasetSpec
from cfi.market.universe import ASSET_SYMBOLS

# Assets with US spot ETFs reported by the provider (SoSoValue documentation, 2026-09-24).
ETF_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")
# Listed-company holdings tracked per coin (CoinGecko public treasury, documented coin ids).
TREASURY_HOLDING_ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL")
# Dated per-company purchase history is available for bitcoin only (SoSoValue BTC Treasuries).
TREASURY_PURCHASE_ASSETS: tuple[str, ...] = ("BTC",)

assert set(ETF_ASSETS) <= set(ASSET_SYMBOLS)  # noqa: S101 — static configuration check

# ETF flows for trading date D are treated as public at 18:00 New York time on the next US trading
# day (conservative estimate; values actually received earlier are dated by receipt). The
# receipt times of natively ingested rows will show how early they really appear (ADR-0048).
ETF_AVAILABILITY = AvailabilityRule(
    "next_us_trading_day", timedelta(hours=18), known_when_received=True
)
# Company purchase disclosures: listed companies typically disclose within days (weekly summaries,
# or current reports due within four business days). Seven calendar days is the conservative
# estimate; purchases actually received earlier are dated by receipt.
TREASURY_PURCHASE_AVAILABILITY = AvailabilityRule(
    "event_time_plus", timedelta(days=7), known_when_received=True
)

# Freshness limits used by the ingestion engine (calendar-aware freshness is computed on read).
ETF_FRESHNESS_LIMIT = timedelta(days=5)

ETF_FLOW_US_SPOT = DatasetSpec(
    dataset_id="institutional.etf_flow.us_spot.1d",
    metric="etf_flow",
    unit="usd",
    period="1d",
    availability=ETF_AVAILABILITY,
    freshness_limit=ETF_FRESHNESS_LIMIT,
    conflict_tolerance=Decimal("0.01"),
    revisable=True,
    kind="flow",
    description=(
        "Daily net flow of all US spot ETFs of one asset, as totalled by the provider: "
        "flow_usd = net inflow (creations - redemptions, USD), holdings_usd = total net assets "
        "(USD), cum_flow_usd = cumulative net inflow since launch, value_traded_usd = total "
        "value traded. event_time = US trading date (00:00 UTC label)."
    ),
)

ETF_FUND_FLOW_US_SPOT = DatasetSpec(
    dataset_id="institutional.etf_fund_flow.us_spot.1d",
    metric="etf_flow",
    unit="usd",
    period="1d",
    availability=ETF_AVAILABILITY,
    freshness_limit=ETF_FRESHNESS_LIMIT,
    conflict_tolerance=Decimal("0.01"),
    revisable=True,
    kind="flow",
    description=(
        "Daily net flow of one US spot ETF: flow_usd = net inflow (USD), holdings_usd = net "
        "assets (USD), cum_flow_usd = cumulative net inflow, value_traded_usd = value traded "
        "(USD), premium_discount = market price premium (+) / discount (-) to NAV as a ratio. "
        "event_time = US trading date (00:00 UTC label)."
    ),
)

TREASURY_PURCHASE_BTC = DatasetSpec(
    dataset_id="institutional.treasury_purchase.btc",
    metric="treasury_purchase",
    unit="usd",
    period="event",
    availability=TREASURY_PURCHASE_AVAILABILITY,
    # Only classifies pit_reliability (stored within 3 days of becoming public = native). Ingestion
    # jobs do not check freshness for sporadic events (check_freshness=False).
    freshness_limit=timedelta(days=3),
    conflict_tolerance=Decimal("0.01"),
    revisable=True,
    kind="flow",
    check_freshness=False,
    description=(
        "Bitcoin acquisitions disclosed by one listed company, as compiled by the provider: "
        "flow_native = BTC acquired (negative = sold), flow_usd = acquisition cost (USD), "
        "holdings_native = company BTC holdings after the "
        "transaction. event_time = purchase date given by the provider (00:00 UTC label)."
    ),
)

TREASURY_HOLDINGS_COMPANIES = DatasetSpec(
    dataset_id="institutional.treasury_holdings.public_companies",
    metric="treasury_holdings",
    unit="usd",
    period="event",
    availability=AvailabilityRule("provider"),
    freshness_limit=timedelta(hours=26),
    conflict_tolerance=Decimal("0.01"),
    revisable=True,
    kind="flow",
    description=(
        "Total holdings of all listed companies the provider tracks for one coin: "
        "holdings_native = coins held, holdings_usd = current value (USD). event_time = time "
        "the snapshot was received (the provider updates it about every 5 minutes)."
    ),
)


def all_datasets() -> list[DatasetSpec]:
    return [
        ETF_FLOW_US_SPOT,
        ETF_FUND_FLOW_US_SPOT,
        TREASURY_PURCHASE_BTC,
        TREASURY_HOLDINGS_COMPANIES,
    ]


def dataset_by_id(dataset_id: str) -> DatasetSpec:
    for spec in all_datasets():
        if spec.dataset_id == dataset_id:
            return spec
    raise KeyError(dataset_id)


def etf_group_ref(asset: str) -> str:
    return f"US-SPOT-ETF:{asset}"


def etf_fund_ref(ticker: str) -> str:
    return f"ETF:{ticker}"


def company_ref(ticker: str) -> str:
    return f"COMPANY:{ticker}"


def companies_group_ref(asset: str) -> str:
    return f"PUBLIC-COMPANIES:{asset}"
