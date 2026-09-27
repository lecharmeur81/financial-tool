"""Macroeconomic datasets (Phase 11): rates, inflation, growth, risk appetite and US liquidity
proxies — every series sourced from FRED (Federal Reserve Economic Data, St. Louis Fed), verified
2026-09-27 against the official documentation (``fred.stlouisfed.org/docs/api/fred/...`` and each
series' own FRED page — ``fred.stlouisfed.org`` itself is unreachable from this sandboxed
workspace's egress proxy, confirmed via direct ``curl`` returning ``403``, so live response shapes
are verified from documentation and cross-referenced series pages, not a live payload; joins the
same pattern already recorded for Blockchair (Phase 7), Binance (Phase 8) and DefiLlama (Phase 9)
— real ingestion is verified on the user's own first run, per that established precedent).

**Two labelled substitutions/scope decisions, stated plainly rather than silently narrowed (R3):**

- **"DXY" → ``DTWEXBGS`` (Nominal Broad U.S. Dollar Index).** The real ICE US Dollar Index (DXY)
  is a proprietary, licensed index with no free public API. ``DTWEXBGS`` is the Federal Reserve's
  own free, publicly documented trade-weighted dollar index against a broad basket of currencies —
  a different, broader basket than DXY's six currencies, moving similarly in direction but **not
  numerically the same series**. Every place this is shown is labelled "Broad Dollar Index
  (DXY substitute)", never "DXY".
- **"Global liquidity proxies" → US-only.** A genuinely multi-central-bank aggregate (Fed + ECB +
  BOJ + PBOC balance sheets) would need additional sources not yet verified here. What is tracked
  is a commonly cited **US net liquidity** proxy (Fed balance sheet − Treasury General Account −
  overnight reverse repo) plus US M2 money supply (weekly and monthly cadences) — labelled
  "US liquidity proxies" everywhere, never presented as a true global aggregate. Recorded as a
  scope decision for the user's review (``TODO.md``), not a silent omission.

**Not tracked, and said so** (``NOT_TRACKED``):

- **Gold spot price.** FRED's only free daily gold series (LBMA AM/PM fixing,
  ``GOLDAMGBD228NLBM`` / ``GOLDPMGBD228NLBM``) was discontinued in January 2022 — ICE Benchmark
  Administration, the data's rights holder, required its removal from FRED (confirmed via FRED's
  own announcement). No other **verified, officially documented, $0/keyless** gold-price source
  was found in this build; every free alternative located (see e.g. goldprice.dev, GoldAPI.io,
  api-ninjas) is an unofficial third-party aggregator whose data provenance and terms could not be
  verified against a reputable primary source, the same posture this project already takes toward
  unauthorised/unverified scraping (``cfi.retail.universe``'s Google Trends decision). A business
  decision for the user: adopt one of those services (and its terms), or fund a paid provider.

**Point-in-time integrity for revised series (CPI, PCE, unemployment, M2) — a stated, accepted
limitation, not built out further (R13):** FRED's default API exposes only the *current* vintage
of each historical value, not what was originally published on the release date (seasonal-
adjustment updates and benchmark revisions happen after the fact). FRED does expose true
vintage/point-in-time data via ``realtime_start``/``realtime_end``/``vintage_dates`` (confirmed in
the official docs), so building genuine ALFRED-style revision-safe backtesting is possible if
requested later — not built here, to avoid over-engineering an unrequested feature. What *is* built
is a conservative, documented **release-schedule delay** per revised series (``available_at``
estimated from each series' real, publicly documented release-lag, flagged
``available_at_estimated=True``), which prevents look-ahead bias in the simple sense (never
treating a monthly print as knowable before its real release date) without vintage-level revision
tracking. Every value returned for a past month is FRED's *current* (most revised) figure, stated
as such — never presented as point-in-time-exact for the deep-revision sense.

**Timestamp normalisation ("Normalize all macro timestamps"):** every dataset below stores
``event_time`` as the observation's calendar date at UTC midnight (FRED's own convention: a daily
series is dated the trading/business day, a weekly series the "as of" day — mostly Wednesdays —
and a monthly series the first of the month), regardless of source frequency. ``period`` records
the true cadence (``"1d"``, ``"1w"``, ``"1mo"`` or ``"event"``, see ``cfi.core.time.parse_period``
— ``"1mo"`` added in this phase as a nominal 30-day scheduling bucket, never used for exact
calendar-month math) so daily/weekly/monthly/event-based data are all explicitly distinguished and
queryable on their own terms, per the phase's "Support: daily / weekly / monthly / event-based
data" requirement.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from cfi.domain.datasets import AvailabilityRule, DatasetSpec

# Every FRED series id used, one place, so the adapter and this registry can't drift apart.
FRED_SERIES: dict[str, str] = {
    "macro.dxy_broad_proxy.1d": "DTWEXBGS",
    "macro.ust_yield_2y.1d": "DGS2",
    "macro.ust_yield_10y.1d": "DGS10",
    "macro.fed_funds_effective.1d": "DFF",
    "macro.vix.1d": "VIXCLS",
    "macro.sp500.1d": "SP500",
    "macro.nasdaq_composite.1d": "NASDAQCOM",
    "macro.oil_wti.1d": "DCOILWTICO",
    "macro.reverse_repo.1d": "RRPONTSYD",
    "macro.fed_balance_sheet.1w": "WALCL",
    "macro.treasury_general_account.1w": "WTREGEN",
    "macro.m2_money_stock.1w": "WM2NS",
    "macro.cpi.1mo": "CPIAUCSL",
    "macro.pce_price_index.1mo": "PCEPI",
    "macro.unemployment_rate.1mo": "UNRATE",
    "macro.m2_money_stock.1mo": "M2SL",
    "macro.fed_funds_target_upper.event": "DFEDTARU",
    "macro.fed_funds_target_lower.event": "DFEDTARL",
}

# A single sentinel "subject": every macro series is one nationwide (US) time series, not keyed by
# asset or venue — there is nothing to disambiguate per request, unlike every other module in this
# project (mirrors retail/universe.py's TRENDING_SUBJECT sentinel for the same reason).
US_SUBJECT = "US"

NOT_TRACKED: tuple[dict[str, str], ...] = (
    {
        "item": "Gold spot price",
        "reason": "FRED's only free daily gold series (LBMA fixing, GOLDAMGBD228NLBM / "
        "GOLDPMGBD228NLBM) was discontinued in January 2022 at the rights holder's (ICE "
        "Benchmark Administration) request. No other verified, officially documented, $0/keyless "
        "gold-price source was found; every free alternative located is an unofficial "
        "third-party aggregator whose provenance and terms are unverified. A business decision "
        "for the user.",
    },
    {
        "item": "True global liquidity aggregate (Fed + ECB + BOJ + PBOC)",
        "reason": "Only US components are tracked (Fed balance sheet, TGA, reverse repo, M2). A "
        "genuine multi-central-bank aggregate would need additional sources (ECB/BOJ/PBOC "
        "balance sheets) not yet verified here — a scope decision, not a silent gap.",
    },
)

# ---------------------------------------------------------------------------- availability rules

# Daily market-style series: FRED typically publishes the prior business day's value the next
# business day (H.15/H.10-style releases). A conservative 1-day delay; period_end_plus cannot be
# combined with known_when_received (cfi.domain.datasets.AvailabilityRule.__post_init__), so an
# unusually early real publish is not specially trusted here — the same posture every other daily
# bar-like dataset in this project already takes.
_DAILY_MARKET = AvailabilityRule("period_end_plus", timedelta(days=1))

# Weekly series (Fed balance sheet, TGA, weekly M2): "as of" a fixed weekday, published a few days
# later. A conservative 3-day delay covers the observed 1-day (WALCL: Wed value, Thu release) up to
# slower weekly releases without needing a per-series delay.
_WEEKLY = AvailabilityRule("period_end_plus", timedelta(days=3))

# Monthly, revised economic series: real, documented BLS/BEA release-schedule delays, measured from
# the *start* of the reference month (event_time), not from a nominal period length — see module
# docstring's "Point-in-time integrity" note. known_when_received=True: if FRED already returned a
# value, it was genuinely released (our estimate is a conservative floor, never a reason to reject
# a value FRED actually delivered).
_CPI_DELAY = AvailabilityRule("event_time_plus", timedelta(days=45), known_when_received=True)
_PCE_DELAY = AvailabilityRule("event_time_plus", timedelta(days=60), known_when_received=True)
_UNEMPLOYMENT_DELAY = AvailabilityRule(
    "event_time_plus", timedelta(days=38), known_when_received=True
)
_M2_MONTHLY_DELAY = AvailabilityRule(
    "event_time_plus", timedelta(days=52), known_when_received=True
)

# Event-based (FOMC rate-decision series): FRED publishes daily, but the value only ever changes on
# an actual FOMC decision date; a 1-day estimated delay, same trust rule as the monthly series.
_FOMC_EVENT = AvailabilityRule("event_time_plus", timedelta(days=1), known_when_received=True)

# ---------------------------------------------------------------------------- dataset specs

DXY_BROAD_PROXY = DatasetSpec(
    dataset_id="macro.dxy_broad_proxy.1d",
    metric="dxy_broad_proxy",
    unit="index",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("0.5"),
    revisable=False,
    kind="scalar",
    description=(
        "Nominal Broad U.S. Dollar Index (FRED DTWEXBGS) — a free, publicly documented DXY "
        "SUBSTITUTE, not the licensed ICE US Dollar Index itself (different currency basket; "
        "see module docstring)."
    ),
)

UST_YIELD_2Y = DatasetSpec(
    dataset_id="macro.ust_yield_2y.1d",
    metric="ust_yield_2y",
    unit="percent",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("0.02"),
    revisable=False,
    kind="scalar",
    description="Market yield on 2-year U.S. Treasury securities, constant maturity (FRED DGS2).",
)

UST_YIELD_10Y = DatasetSpec(
    dataset_id="macro.ust_yield_10y.1d",
    metric="ust_yield_10y",
    unit="percent",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("0.02"),
    revisable=False,
    kind="scalar",
    description="Market yield on 10-year U.S. Treasury securities, constant maturity (FRED DGS10).",
)

FED_FUNDS_EFFECTIVE = DatasetSpec(
    dataset_id="macro.fed_funds_effective.1d",
    metric="fed_funds_effective",
    unit="percent",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("0.02"),
    revisable=False,
    kind="scalar",
    description="Daily effective federal funds rate (FRED DFF).",
)

VIX = DatasetSpec(
    dataset_id="macro.vix.1d",
    metric="vix",
    unit="index",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("0.5"),
    revisable=False,
    kind="scalar",
    description="CBOE Volatility Index, close (FRED VIXCLS).",
)

SP500 = DatasetSpec(
    dataset_id="macro.sp500.1d",
    metric="sp500",
    unit="index",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("5"),
    revisable=False,
    kind="scalar",
    description="S&P 500 index, close (FRED SP500).",
)

NASDAQ_COMPOSITE = DatasetSpec(
    dataset_id="macro.nasdaq_composite.1d",
    metric="nasdaq_composite",
    unit="index",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("10"),
    revisable=False,
    kind="scalar",
    description="NASDAQ Composite Index, close (FRED NASDAQCOM).",
)

OIL_WTI = DatasetSpec(
    dataset_id="macro.oil_wti.1d",
    metric="oil_wti",
    unit="usd_per_barrel",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("0.5"),
    revisable=False,
    kind="scalar",
    description="WTI Crude Oil, spot price, Cushing OK (FRED DCOILWTICO).",
)

REVERSE_REPO = DatasetSpec(
    dataset_id="macro.reverse_repo.1d",
    metric="reverse_repo",
    unit="usd_billions",
    period="1d",
    availability=_DAILY_MARKET,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("1"),
    revisable=False,
    kind="scalar",
    description=(
        "Overnight reverse repurchase agreements, Treasury securities sold by the Federal "
        "Reserve (FRED RRPONTSYD). One component of the US net-liquidity proxy."
    ),
)

FED_BALANCE_SHEET = DatasetSpec(
    dataset_id="macro.fed_balance_sheet.1w",
    metric="fed_balance_sheet",
    unit="usd_millions",
    period="1w",
    availability=_WEEKLY,
    freshness_limit=timedelta(days=10),
    conflict_tolerance=Decimal("1000"),
    revisable=False,
    kind="scalar",
    description=(
        "Federal Reserve total assets, Wednesday level (FRED WALCL). One component of the US "
        "net-liquidity proxy."
    ),
)

TREASURY_GENERAL_ACCOUNT = DatasetSpec(
    dataset_id="macro.treasury_general_account.1w",
    metric="treasury_general_account",
    unit="usd_millions",
    period="1w",
    availability=_WEEKLY,
    freshness_limit=timedelta(days=10),
    conflict_tolerance=Decimal("1000"),
    revisable=False,
    kind="scalar",
    description=(
        "US Treasury General Account balance held at the Federal Reserve (FRED WTREGEN). One "
        "component of the US net-liquidity proxy."
    ),
)

M2_WEEKLY = DatasetSpec(
    dataset_id="macro.m2_money_stock.1w",
    metric="m2_money_stock_weekly",
    unit="usd_billions",
    period="1w",
    availability=_WEEKLY,
    freshness_limit=timedelta(days=12),
    conflict_tolerance=Decimal("5"),
    revisable=True,
    kind="scalar",
    description="M2 money stock, weekly, not seasonally adjusted (FRED WM2NS).",
)

CPI = DatasetSpec(
    dataset_id="macro.cpi.1mo",
    metric="cpi",
    unit="index",
    period="1mo",
    availability=_CPI_DELAY,
    freshness_limit=timedelta(days=60),
    conflict_tolerance=Decimal("0.5"),
    revisable=True,
    kind="scalar",
    description=(
        "Consumer Price Index for All Urban Consumers: All Items, seasonally adjusted (FRED "
        "CPIAUCSL). event_time = first day of the reference month; available_at is estimated "
        "from BLS's real release schedule (~45 days after the reference month starts), not FRED's "
        "own timestamp — see module docstring."
    ),
)

PCE_PRICE_INDEX = DatasetSpec(
    dataset_id="macro.pce_price_index.1mo",
    metric="pce_price_index",
    unit="index",
    period="1mo",
    availability=_PCE_DELAY,
    freshness_limit=timedelta(days=75),
    conflict_tolerance=Decimal("0.5"),
    revisable=True,
    kind="scalar",
    description=(
        "Personal Consumption Expenditures: Chain-type Price Index (FRED PCEPI). event_time = "
        "first day of the reference month; available_at estimated from BEA's real release "
        "schedule (~60 days after the reference month starts)."
    ),
)

UNEMPLOYMENT_RATE = DatasetSpec(
    dataset_id="macro.unemployment_rate.1mo",
    metric="unemployment_rate",
    unit="percent",
    period="1mo",
    availability=_UNEMPLOYMENT_DELAY,
    freshness_limit=timedelta(days=50),
    conflict_tolerance=Decimal("0.1"),
    revisable=True,
    kind="scalar",
    description=(
        "Civilian unemployment rate, seasonally adjusted (FRED UNRATE). event_time = first day "
        "of the reference month; available_at estimated from BLS's Employment Situation release "
        "schedule (first Friday of the following month, ~38 days after the reference month "
        "starts, conservative)."
    ),
)

M2_MONTHLY = DatasetSpec(
    dataset_id="macro.m2_money_stock.1mo",
    metric="m2_money_stock_monthly",
    unit="usd_billions",
    period="1mo",
    availability=_M2_MONTHLY_DELAY,
    freshness_limit=timedelta(days=65),
    conflict_tolerance=Decimal("5"),
    revisable=True,
    kind="scalar",
    description="M2 money stock, monthly, seasonally adjusted (FRED M2SL).",
)

FED_FUNDS_TARGET_UPPER = DatasetSpec(
    dataset_id="macro.fed_funds_target_upper.event",
    metric="fed_funds_target_upper",
    unit="percent",
    period="event",
    availability=_FOMC_EVENT,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("0"),
    revisable=False,
    kind="scalar",
    check_freshness=False,  # value is unchanged between meetings — its age says nothing about
    # pipeline health, matching the sporadic-event convention (cfi.domain.datasets.DatasetSpec).
    description=(
        "Federal funds target range, upper bound (FRED DFEDTARU). Published daily by FRED but "
        "only actually changes on an FOMC decision date — tracked as event-based data."
    ),
)

FED_FUNDS_TARGET_LOWER = DatasetSpec(
    dataset_id="macro.fed_funds_target_lower.event",
    metric="fed_funds_target_lower",
    unit="percent",
    period="event",
    availability=_FOMC_EVENT,
    freshness_limit=timedelta(days=4),
    conflict_tolerance=Decimal("0"),
    revisable=False,
    kind="scalar",
    check_freshness=False,
    description="Federal funds target range, lower bound (FRED DFEDTARL). See upper-bound note.",
)


def all_datasets() -> list[DatasetSpec]:
    return [
        DXY_BROAD_PROXY,
        UST_YIELD_2Y,
        UST_YIELD_10Y,
        FED_FUNDS_EFFECTIVE,
        VIX,
        SP500,
        NASDAQ_COMPOSITE,
        OIL_WTI,
        REVERSE_REPO,
        FED_BALANCE_SHEET,
        TREASURY_GENERAL_ACCOUNT,
        M2_WEEKLY,
        CPI,
        PCE_PRICE_INDEX,
        UNEMPLOYMENT_RATE,
        M2_MONTHLY,
        FED_FUNDS_TARGET_UPPER,
        FED_FUNDS_TARGET_LOWER,
    ]


def dataset_by_id(dataset_id: str) -> DatasetSpec:
    for spec in all_datasets():
        if spec.dataset_id == dataset_id:
            return spec
    raise KeyError(dataset_id)


def fred_series_id(dataset_id: str) -> str:
    try:
        return FRED_SERIES[dataset_id]
    except KeyError:
        raise KeyError(f"no FRED series mapped for dataset {dataset_id!r}") from None
