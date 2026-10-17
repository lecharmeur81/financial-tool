"""Deterministic synthetic history for the Phase 51 seeded ``alerts.evaluate`` benchmark.

**Everything here is synthetic.** No value is, or is derived from, a real market, ETF, on-chain,
derivatives or macroeconomic observation, and none of it may be read as production data or as a
production performance figure. The module exists so the *amount and shape of work* the real
``AlertService.evaluate`` does on a two-year history can be measured on an isolated database.

What it creates (see ``SeedSummary``): the same canonical records the platform's ingestion would
store, written through the platform's own ``IngestionRepository.series_id`` and record stores
(never raw SQL), for every dataset the seven regime inputs read — institutional ETF/treasury flows,
whale/on-chain scalars and labelled addresses, retail trending/small-output counts, stablecoin
liquidity, derivatives (open interest, funding, long/short ratio, liquidations, DVOL), the FRED
macro series, market-structure (daily and hourly bars, market caps, total market cap).

Point-in-time consistency: every record carries the ``available_at`` its dataset rule would give
and an ``ingested_at`` 10 minutes after it, i.e. *backdated* to just after the moment the value
would have been public. A historical query with ``knowledge_time = D`` therefore sees exactly the
records that existed at ``D`` (``ingested_at <= D``), which is what the regime history walk and the
similarity grid ask for.

Determinism: all randomness comes from ``random.Random`` seeded with a string (version-2 seeding,
stable across platforms), only ``+ - * /`` are applied to the drawn floats (no libm functions) and
every value is quantised through ``Decimal`` text, so the same ``SEED`` gives byte-identical
records. ``SeedSummary.fingerprint`` is a SHA-256 over every record written, in write order.
"""

# ruff: noqa: S311 — deterministic, non-cryptographic pseudo-randomness is the whole point here

from __future__ import annotations

import hashlib
import random
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.derivatives.sources import ADAPTERS as DERIVATIVES_ADAPTERS
from cfi.derivatives.sources import PRIORITY as DERIVATIVES_PRIORITY
from cfi.derivatives.sources import SOURCES as DERIVATIVES_SOURCES
from cfi.derivatives.universe import (
    PERP_ASSETS,
    contracts_ref,
    dvol_ref,
    liquidation_ref,
    perp_ref,
)
from cfi.derivatives.universe import dataset as derivatives_dataset
from cfi.domain.datasets import DatasetSpec
from cfi.domain.enums import EvidenceClass, PitReliability, QualityStatus
from cfi.domain.observation import CanonicalBar, CanonicalFlow, CanonicalObservation
from cfi.ingestion.archive import FileSystemArchive
from cfi.ingestion.engine import IngestionEngine
from cfi.ingestion.repository import IngestionRepository
from cfi.institutional.sources import ADAPTERS as INSTITUTIONAL_ADAPTERS
from cfi.institutional.sources import PRIORITY as INSTITUTIONAL_PRIORITY
from cfi.institutional.sources import SOURCES as INSTITUTIONAL_SOURCES
from cfi.institutional.universe import (
    ETF_FLOW_US_SPOT,
    ETF_FUND_FLOW_US_SPOT,
    TREASURY_HOLDINGS_COMPANIES,
    TREASURY_PURCHASE_BTC,
    companies_group_ref,
    company_ref,
    etf_fund_ref,
    etf_group_ref,
)
from cfi.liquidity.sources import ADAPTERS as LIQUIDITY_ADAPTERS
from cfi.liquidity.sources import PRIORITY as LIQUIDITY_PRIORITY
from cfi.liquidity.sources import SOURCES as LIQUIDITY_SOURCES
from cfi.macro.sources import ADAPTERS as MACRO_ADAPTERS
from cfi.macro.sources import PRIORITY as MACRO_PRIORITY
from cfi.macro.sources import SOURCES as MACRO_SOURCES
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.sources import PRIORITY as MARKET_PRIORITY
from cfi.market.sources import datasets_for
from cfi.market.universe import MARKET_CAP_USD, MARKET_CAP_USD_1D, ohlcv_dataset
from cfi.market_structure.sources import ADAPTERS as MS_ADAPTERS
from cfi.market_structure.sources import PRIORITY as MS_PRIORITY
from cfi.market_structure.sources import SOURCES as MS_SOURCES
from cfi.market_structure.universe import TOTAL_MARKET_CAP_USD
from cfi.providers import (
    binance_futures,
    blockchair,
    coinbase,
    coingecko,
    coinmetrics,
    defillama,
    deribit,
    fred,
    okx_derivatives,
    sosovalue,
)
from cfi.retail.sources import ADAPTERS as RETAIL_ADAPTERS
from cfi.retail.sources import PRIORITY as RETAIL_PRIORITY
from cfi.retail.sources import SOURCES as RETAIL_SOURCES
from cfi.retail.universe import SMALL_OUTPUT_COUNT, TRENDING, coin_ref
from cfi.whales.label_store import import_labels
from cfi.whales.labels import CSV_COLUMNS, parse_label_csv
from cfi.whales.sources import ADAPTERS as WHALE_ADAPTERS
from cfi.whales.sources import PRIORITY as WHALE_PRIORITY
from cfi.whales.sources import SOURCES as WHALE_SOURCES
from cfi.whales.universe import address_ref, exchange_ref, network_ref
from cfi.whales.universe import dataset as whale_dataset
from tests.whale_fakes import btc_address

# ----------------------------------------------------------------------------------------------
# Fixed parameters (nothing here is configurable at run time: the benchmark must be comparable).
# ----------------------------------------------------------------------------------------------

SEED = 510_001
SEED_VERSION = "p51-seed-v1"

#: The instant the benchmark evaluates "now". Fixed so the run never depends on the wall clock.
ANCHOR = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)
#: The history the regime walk and the similarity grid can reach back into (~2 years).
ANALYSIS_DAYS = 730
#: Extra daily history before the analysis window so the longest indicators (market structure
#: loads 430 days; macro loads 430 days) have their full look-back at the oldest analysed date.
WARMUP_DAYS = 440
DAILY_DAYS = ANALYSIS_DAYS + WARMUP_DAYS
FIRST_DAY: date = ANCHOR.date() - timedelta(days=DAILY_DAYS)
#: Depth of the hourly series (open interest, long/short ratio, liquidations, hourly bars, event
#: market caps). The providers' own back-fill limits are ~29 days (Binance/OKX open interest and
#: account ratio) and liquidations are live-only, so the default is provider-limited; how much
#: live history a production database has accumulated beyond that is NOT known here. The
#: stress scenario (``hourly_days=ANALYSIS_DAYS + 10``) gives every hourly series two full years.
DEFAULT_HOURLY_DAYS = 40
MAX_HOURLY_DAYS = ANALYSIS_DAYS + 10
#: Funding rate (back-fill limit 365 d at Binance) and DVOL (365 d at Deribit) go deeper.
SLOW_HOURLY_DAYS = 375
INGEST_DELAY = timedelta(minutes=10)
BATCH = 2_000

ASSETS: tuple[str, ...] = ("BTC", "ETH", "SOL", "XRP")
PRICE0 = {"BTC": 42_000.0, "ETH": 2_400.0, "SOL": 95.0, "XRP": 0.55}
BETA = {"BTC": 1.0, "ETH": 1.1, "SOL": 1.3, "XRP": 1.1}
DAILY_VOL = {"BTC": 0.022, "ETH": 0.028, "SOL": 0.04, "XRP": 0.035}
SUPPLY = {"BTC": 19_600_000.0, "ETH": 120_000_000.0, "SOL": 440_000_000.0, "XRP": 55e9}
OI_BASE = {"BTC": 280_000.0, "ETH": 7_000_000.0, "SOL": 40_000_000.0, "XRP": 3e9}

SYNTHETIC_ETFS = ("SYNA", "SYNB")
SYNTHETIC_COMPANIES = ("SYNCO1", "SYNCO2", "SYNCO3")
TRENDING_COINS = {"BTC": "bitcoin", "DOGE": "doge", "PEPE": "pepe", "SHIB": "shib"}
# A single synthetic label file: two exchange/government wallets + ten unlabelled large holders.
EXCHANGE_WALLET = btc_address(1001)
GOVERNMENT_WALLET = btc_address(1002)
UNLABELLED_WALLETS = tuple(btc_address(i) for i in range(10))
WHALE_ADDRESSES = (EXCHANGE_WALLET, GOVERNMENT_WALLET, *UNLABELLED_WALLETS)

UTC_MIDNIGHT = time(0, 0)


def _dec(value: float, places: int = 8) -> Decimal:
    """Quantise through text so the stored value never depends on float repr subtleties."""
    return Decimal(f"{value:.{places}f}")


def day_start(index: int) -> datetime:
    return datetime.combine(FIRST_DAY + timedelta(days=index), UTC_MIDNIGHT, tzinfo=UTC)


def _noise(rng: random.Random) -> float:
    """Irwin-Hall(4) minus its mean: roughly bell-shaped, sd ~0.58, built from ``+`` only."""
    return rng.random() + rng.random() + rng.random() + rng.random() - 2.0


def _segments(
    rng: random.Random, n: int, lo: int, hi: int, vmin: float, vmax: float
) -> list[float]:
    """Piecewise-linear path through random knots 'lo..hi' days apart (regime-like swings)."""
    knots: list[tuple[int, float]] = []
    pos = 0
    while pos < n + hi:
        knots.append((pos, rng.uniform(vmin, vmax)))
        pos += rng.randint(lo, hi)
    out: list[float] = []
    k = 0
    for i in range(n):
        while knots[k + 1][0] <= i:
            k += 1
        (x0, y0), (x1, y1) = knots[k], knots[k + 1]
        out.append(y0 + (y1 - y0) * (i - x0) / (x1 - x0))
    return out


@dataclass(frozen=True, slots=True)
class Latents:
    """Shared slow-moving drivers. Different segment lengths and independent draws make
    institutional and retail positioning diverge for stretches, so the history contains varied
    regimes (otherwise the similarity search would only ever see one repeated state)."""

    trend: list[float]
    inst: list[float]
    retail: list[float]
    lev: list[float]
    liquidity: list[float]
    macro: list[float]
    price: dict[str, list[float]]

    @classmethod
    def build(cls, n: int) -> Latents:
        rng = random.Random(f"{SEED}:latents")
        trend = _segments(rng, n, 30, 90, -1.0, 1.0)
        inst_own = _segments(rng, n, 20, 60, -1.0, 1.0)
        retail_own = _segments(rng, n, 15, 50, 0.0, 1.0)
        lev = _segments(rng, n, 10, 40, 0.1, 1.0)
        liquidity = _segments(rng, n, 40, 120, -1.0, 1.0)
        macro = _segments(rng, n, 60, 150, -1.0, 1.0)
        inst = [0.5 * trend[i] + 0.5 * inst_own[i] for i in range(n)]
        retail = [
            min(1.0, max(0.0, 0.4 * retail_own[i] + 0.3 * (trend[i] + 1.0))) for i in range(n)
        ]
        price: dict[str, list[float]] = {}
        for asset in ASSETS:
            prng = random.Random(f"{SEED}:price:{asset}")
            p = PRICE0[asset]
            path: list[float] = []
            for i in range(n):
                p *= 1.0 + BETA[asset] * 0.004 * trend[i] + DAILY_VOL[asset] * _noise(prng)
                p = max(p, PRICE0[asset] * 0.05)
                path.append(p)
            price[asset] = path
        return cls(trend, inst, retail, lev, liquidity, macro, price)


# ----------------------------------------------------------------------------------------------
# Registrations (the same datasets / providers the platform's own harnesses register)
# ----------------------------------------------------------------------------------------------


def registrations() -> list[tuple[DatasetSpec, object, int]]:
    out: list[tuple[DatasetSpec, object, int]] = []
    seen: set[tuple[str, str]] = set()

    def add(spec: DatasetSpec, adapter: object, priority: int, provider: str) -> None:
        if (spec.dataset_id, provider) not in seen:
            seen.add((spec.dataset_id, provider))
            out.append((spec, adapter, priority))

    groups: Sequence[tuple[Sequence[Any], Mapping[str, Any], Mapping[str, int]]] = (
        (INSTITUTIONAL_SOURCES, INSTITUTIONAL_ADAPTERS, INSTITUTIONAL_PRIORITY),
        (WHALE_SOURCES, WHALE_ADAPTERS, WHALE_PRIORITY),
        (RETAIL_SOURCES, RETAIL_ADAPTERS, RETAIL_PRIORITY),
        (LIQUIDITY_SOURCES, LIQUIDITY_ADAPTERS, LIQUIDITY_PRIORITY),
        (MACRO_SOURCES, MACRO_ADAPTERS, MACRO_PRIORITY),
        (MS_SOURCES, MS_ADAPTERS, MS_PRIORITY),
        (DERIVATIVES_SOURCES, DERIVATIVES_ADAPTERS, DERIVATIVES_PRIORITY),
    )
    for sources, adapters, priorities in groups:
        for item in sources:
            provider = item.provider_id
            add(item.dataset, adapters[provider], priorities[provider], provider)
    for provider_id, adapter in MARKET_ADAPTERS.items():
        for spec in datasets_for(provider_id):
            add(spec, adapter, MARKET_PRIORITY[provider_id], provider_id)
    return out


# ----------------------------------------------------------------------------------------------
# Record timing and builders
# ----------------------------------------------------------------------------------------------

_FAR = timedelta(days=400)


def _timing(
    spec: DatasetSpec, event: datetime, provider_lag: timedelta = timedelta(minutes=5)
) -> tuple[datetime, bool, datetime]:
    """``(available_at, estimated, ingested_at)`` the dataset's own rule gives for ``event``.

    ``ingested_at`` is backdated to ``available_at + 10 min``: the record "was stored" right after
    the value became public, exactly like a healthy live pipeline would have stored it."""
    if spec.availability.kind == "provider":
        available, estimated = event + provider_lag, False
    else:
        available, estimated = spec.available_at(event, None, event + _FAR)
        period = spec.period_length
        if (
            spec.availability.known_when_received
            and period is not None
            and period <= timedelta(days=1)
        ):
            # A snapshot that is final whenever it is published: it was stored when received, an
            # hour after its label, not at the (late, conservative) rule-based estimate.
            available = min(available, event + timedelta(hours=1))
    return available, estimated, available + INGEST_DELAY


class Collector:
    """Accumulates the fingerprint and per-table counts of everything written."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self.counts: dict[str, int] = {}
        self.families: dict[str, int] = {}
        self.dropped_after_anchor = 0

    def add(self, table: str, family: str, record: object, line: str) -> None:
        self._digest.update(line.encode())
        self._digest.update(b"\n")
        self.counts[table] = self.counts.get(table, 0) + 1
        self.families[family] = self.families.get(family, 0) + 1

    def hexdigest(self) -> str:
        return self._digest.hexdigest()


def _line(r: CanonicalObservation | CanonicalBar | CanonicalFlow, values: object) -> str:
    return (
        f"{r.dataset_id}|{r.subject_ref}|{r.venue}|{r.event_time.isoformat()}|"
        f"{r.available_at.isoformat()}|{r.ingested_at.isoformat()}|{r.source_provider}|{values!r}"
    )


@dataclass(slots=True)
class SeedSummary:
    seed: int
    seed_version: str
    hourly_days: int
    anchor: datetime
    first_day: date
    daily_days: int
    analysis_days: int
    fingerprint: str
    table_counts: dict[str, int]
    family_counts: dict[str, int]
    series_count: int = 0
    notes: list[str] = field(default_factory=list)


class Seeder:
    def __init__(
        self,
        engine: AsyncEngine | None = None,
        raw_dir: object = None,
        hourly_days: int = DEFAULT_HOURLY_DAYS,
    ) -> None:
        """``engine=None`` is a *dry run*: every record is generated and fingerprinted but nothing
        is registered or written (used to prove determinism without any database)."""
        if not 10 <= hourly_days <= MAX_HOURLY_DAYS:
            raise ValueError(f"hourly_days must be within 10..{MAX_HOURLY_DAYS}")
        self.hourly_days = hourly_days
        self.engine = engine
        self.dry = engine is None
        if engine is not None:
            self.repo = IngestionRepository(engine)
            self.ingestion = IngestionEngine(self.repo, FileSystemArchive(raw_dir))  # type: ignore[arg-type]
            self.stores = self.ingestion._stores
        self.lat = Latents.build(DAILY_DAYS)
        self.col = Collector()
        self.col._digest.update(f"{SEED_VERSION}|{SEED}|hourly_days={hourly_days}\n".encode())
        self.series = 0
        self._specs: dict[str, DatasetSpec] = {}

    # -- plumbing -------------------------------------------------------------------------

    def spec(self, dataset_id: str) -> DatasetSpec:
        return self._specs[dataset_id]

    async def register_all(self) -> None:
        for spec, adapter, priority in registrations():
            self._specs[spec.dataset_id] = spec
            if not self.dry:
                await self.ingestion.register(spec, adapter, priority)  # type: ignore[arg-type]

    async def _write(self, kind: str, family: str, records: list[tuple[object, str]]) -> None:
        """Write one series: ``records`` are ``(record, fingerprint_line)`` in event-time order."""
        kept = [r for r in records if r[0].ingested_at <= ANCHOR]  # type: ignore[attr-defined]
        self.col.dropped_after_anchor += len(records) - len(kept)
        if not kept:
            return
        self.series += 1
        table = {
            "scalar": "obs.observation",
            "bar": "obs.market_bar",
            "flow": "obs.institutional_flow",
        }[kind]
        if not self.dry:
            sid = await self.repo.series_id(kept[0][0])  # type: ignore[arg-type]
            store = self.stores[kind]
            for start in range(0, len(kept), BATCH):
                chunk = kept[start : start + BATCH]
                await store.insert([(sid, r) for r, _ in chunk])  # type: ignore[misc]
        for record, line in kept:
            self.col.add(table, family, record, line)

    def _obs(
        self,
        dataset_id: str,
        *,
        asset: str,
        subject: str,
        venue: str | None,
        provider: str,
        original: str,
        event: datetime,
        value: float | Decimal,
        places: int = 8,
        provider_lag: timedelta = timedelta(minutes=5),
    ) -> tuple[CanonicalObservation, str]:
        spec = self.spec(dataset_id)
        available, estimated, ingested = _timing(spec, event, provider_lag)
        val = value if isinstance(value, Decimal) else _dec(value, places)
        rec = CanonicalObservation(
            dataset_id=spec.dataset_id,
            metric=spec.metric,
            asset=asset,
            subject_ref=subject,
            venue=venue,
            period=spec.period,
            unit=spec.unit,
            event_time=event,
            available_at=available,
            available_at_estimated=estimated,
            ingested_at=ingested,
            source_provider=provider,
            original_source=original,
            quality_status=QualityStatus.OK,
            pit_reliability=PitReliability.NATIVE,
            value=val,
        )
        return rec, _line(rec, val)

    def _bar(
        self,
        dataset_id: str,
        *,
        asset: str,
        subject: str,
        event: datetime,
        o: float,
        h: float,
        lo: float,
        c: float,
        volume: float,
    ) -> tuple[CanonicalBar, str]:
        spec = self.spec(dataset_id)
        available, estimated, ingested = _timing(spec, event)
        vals = (_dec(o, 6), _dec(h, 6), _dec(lo, 6), _dec(c, 6), _dec(volume, 6))
        rec = CanonicalBar(
            dataset_id=spec.dataset_id,
            metric=spec.metric,
            asset=asset,
            subject_ref=subject,
            venue="coinbase",
            period=spec.period,
            unit=spec.unit,
            event_time=event,
            available_at=available,
            available_at_estimated=estimated,
            ingested_at=ingested,
            source_provider=coinbase.PROVIDER_ID,
            original_source="coinbase",
            quality_status=QualityStatus.OK,
            pit_reliability=PitReliability.NATIVE,
            open=vals[0],
            high=vals[1],
            low=vals[2],
            close=vals[3],
            volume_base=vals[4],
            volume_quote=_dec(volume * c, 2),
            trade_count=int(volume / 5) + 1,
        )
        return rec, _line(rec, (vals, rec.volume_quote, rec.trade_count))

    def _flow(
        self,
        dataset_id: str,
        *,
        asset: str,
        subject: str,
        entity_type: str,
        evidence: EvidenceClass,
        name: str,
        provider: str,
        original: str,
        event: datetime,
        **amounts: Decimal | None,
    ) -> tuple[CanonicalFlow, str]:
        spec = self.spec(dataset_id)
        available, estimated, ingested = _timing(spec, event)
        rec = CanonicalFlow(
            dataset_id=spec.dataset_id,
            metric=spec.metric,
            asset=asset,
            subject_ref=subject,
            venue=None,
            period=spec.period,
            unit=spec.unit,
            event_time=event,
            available_at=available,
            available_at_estimated=estimated,
            ingested_at=ingested,
            source_provider=provider,
            original_source=original,
            quality_status=QualityStatus.OK,
            pit_reliability=PitReliability.NATIVE,
            entity_type=entity_type,
            evidence_class=evidence,
            entity_name=name,
            **cast("dict[str, Any]", amounts),
        )
        return rec, _line(rec, sorted((k, str(v)) for k, v in amounts.items()))

    # -- calendars --------------------------------------------------------------------------

    def _hours(self, days: int | None = None) -> list[datetime]:
        end = ANCHOR.replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days if days is not None else self.hourly_days)
        n = int((end - start) / timedelta(hours=1))
        return [start + timedelta(hours=i) for i in range(n)]

    def _day_index(self, moment: datetime) -> int:
        return min(DAILY_DAYS - 1, max(0, (moment.date() - FIRST_DAY).days))

    # -- families ---------------------------------------------------------------------------

    async def institutional(self) -> None:
        lat, rng = self.lat, random.Random(f"{SEED}:institutional")
        from cfi.core.calendars import date_label, us_trading_days

        days = us_trading_days(FIRST_DAY, ANCHOR.date())
        scale = {"BTC": 1.0, "ETH": 0.35, "SOL": 0.02, "XRP": 0.015}
        group: dict[str, list[tuple[CanonicalFlow, str]]] = {a: [] for a in ASSETS}
        fund_rows: dict[str, list[tuple[CanonicalFlow, str]]] = {t: [] for t in SYNTHETIC_ETFS}
        cum = dict.fromkeys(ASSETS, 0.0)
        held = {a: 50e9 * scale[a] for a in ASSETS}
        fund_cum = dict.fromkeys(SYNTHETIC_ETFS, 0.0)
        fund_held = {SYNTHETIC_ETFS[0]: 30e9, SYNTHETIC_ETFS[1]: 20e9}
        for day in days:
            i = (day - FIRST_DAY).days
            event = date_label(day)
            for asset in ASSETS:
                flow = scale[asset] * (250e6 * lat.inst[i] + 60e6 * _noise(rng))
                cum[asset] += flow
                held[asset] = max(1e9 * scale[asset], held[asset] + flow)
                traded = scale[asset] * 3e9 * (1.0 + 0.3 * abs(_noise(rng)))
                premium = 0.0004 * _noise(rng)
                group[asset].append(
                    self._flow(
                        ETF_FLOW_US_SPOT.dataset_id,
                        asset=asset,
                        subject=etf_group_ref(asset),
                        entity_type="etf_group",
                        evidence=EvidenceClass.DIRECT,
                        name="US spot ETFs (synthetic)",
                        provider=sosovalue.PROVIDER_ID,
                        original="sosovalue",
                        event=event,
                        flow_usd=_dec(flow, 2),
                        holdings_usd=_dec(held[asset], 2),
                        cum_flow_usd=_dec(cum[asset], 2),
                        value_traded_usd=_dec(traded, 2),
                        premium_discount=_dec(premium, 6),
                    )
                )
                if asset == "BTC":
                    share_a = flow * 0.6
                    for ticker, part in zip(SYNTHETIC_ETFS, (share_a, flow - share_a), strict=True):
                        fund_cum[ticker] += part
                        fund_held[ticker] = max(1e9, fund_held[ticker] + part)
                        fund_rows[ticker].append(
                            self._flow(
                                ETF_FUND_FLOW_US_SPOT.dataset_id,
                                asset="BTC",
                                subject=etf_fund_ref(ticker),
                                entity_type="etf_fund",
                                evidence=EvidenceClass.DIRECT,
                                name=f"Synthetic ETF {ticker}",
                                provider=sosovalue.PROVIDER_ID,
                                original="sosovalue",
                                event=event,
                                flow_usd=_dec(part, 2),
                                holdings_usd=_dec(fund_held[ticker], 2),
                                cum_flow_usd=_dec(fund_cum[ticker], 2),
                                value_traded_usd=_dec(traded * 0.5, 2),
                                premium_discount=_dec(premium, 6),
                            )
                        )
        for asset in ASSETS:
            await self._write("flow", "institutional.etf_flow", group[asset])  # type: ignore[arg-type]
        for ticker in SYNTHETIC_ETFS:
            await self._write("flow", "institutional.etf_fund_flow", fund_rows[ticker])  # type: ignore[arg-type]

        # Treasury purchases (sporadic events) and treasury holdings snapshots.
        for n, ticker in enumerate(SYNTHETIC_COMPANIES):
            holding = [100_000.0, 50_000.0, 20_000.0][n]
            rows: list[tuple[CanonicalFlow, str]] = []
            for i in range(DAILY_DAYS):
                if rng.random() < 0.05 + 0.07 * max(0.0, lat.inst[i]):
                    coins = rng.uniform(100.0, 2_500.0)
                    holding += coins
                    price = lat.price["BTC"][i]
                    rows.append(
                        self._flow(
                            TREASURY_PURCHASE_BTC.dataset_id,
                            asset="BTC",
                            subject=company_ref(ticker),
                            entity_type="public_company",
                            evidence=EvidenceClass.ATTRIBUTED,
                            name=f"Synthetic company {ticker}",
                            provider=sosovalue.PROVIDER_ID,
                            original="sosovalue",
                            event=day_start(i),
                            flow_native=_dec(coins, 4),
                            flow_usd=_dec(coins * price, 2),
                            holdings_native=_dec(holding, 4),
                        )
                    )
            await self._write("flow", "institutional.treasury_purchase", rows)  # type: ignore[arg-type]
        for asset, start_units in (("BTC", 600_000.0), ("ETH", 2_500_000.0), ("SOL", 4_000_000.0)):
            units = start_units
            rows = []
            for i in range(DAILY_DAYS):
                units *= 1.0 + 0.0006 * lat.inst[i]
                event = day_start(i) + timedelta(hours=6)
                rows.append(
                    self._flow(
                        TREASURY_HOLDINGS_COMPANIES.dataset_id,
                        asset=asset,
                        subject=companies_group_ref(asset),
                        entity_type="public_company_group",
                        evidence=EvidenceClass.ATTRIBUTED,
                        name="Public companies (synthetic)",
                        provider=coingecko.PROVIDER_ID,
                        original="coingecko",
                        event=event,
                        holdings_native=_dec(units, 4),
                        holdings_usd=_dec(units * lat.price[asset][i], 2),
                    )
                )
            await self._write("flow", "institutional.treasury_holdings", rows)  # type: ignore[arg-type]

    async def whales(self) -> None:
        lat = self.lat
        rng = random.Random(f"{SEED}:whales")
        flows = {"BTC": 18_000.0, "ETH": 220_000.0}
        exch_start = {"BTC": 2_400_000.0, "ETH": 18_000_000.0}
        supply0 = {"BTC": 19_400_000.0, "ETH": 120_000_000.0}
        daily_issuance = {"BTC": 450.0, "ETH": 1_700.0}
        for asset in ("BTC", "ETH"):
            inflow_rows: list[tuple[CanonicalObservation, str]] = []
            outflow_rows: list[tuple[CanonicalObservation, str]] = []
            exch_rows: list[tuple[CanonicalObservation, str]] = []
            supply_rows: list[tuple[CanonicalObservation, str]] = []
            issuance_rows: list[tuple[CanonicalObservation, str]] = []
            exch = exch_start[asset]
            supply = supply0[asset]
            for i in range(DAILY_DAYS):
                inflow = max(
                    flows[asset] * 0.05,
                    flows[asset] * (1.0 - 0.4 * lat.inst[i] + 0.12 * _noise(rng)),
                )
                outflow = max(
                    flows[asset] * 0.05,
                    flows[asset] * (1.0 + 0.4 * lat.inst[i] + 0.12 * _noise(rng)),
                )
                exch += inflow - outflow
                supply += daily_issuance[asset]
                event = day_start(i)
                common = {
                    "asset": asset,
                    "venue": None,
                    "provider": coinmetrics.PROVIDER_ID,
                    "original": "coinmetrics",
                    "event": event,
                }
                for rows, metric, subject, value in (
                    (inflow_rows, "exchange_inflow", exchange_ref(asset), inflow),
                    (outflow_rows, "exchange_outflow", exchange_ref(asset), outflow),
                    (exch_rows, "exchange_supply", exchange_ref(asset), exch),
                    (supply_rows, "supply", network_ref(asset), supply),
                    (issuance_rows, "issuance", network_ref(asset), daily_issuance[asset]),
                ):
                    rows.append(
                        self._obs(
                            whale_dataset(metric, asset).dataset_id,
                            subject=subject,
                            value=value,
                            **common,  # type: ignore[arg-type]
                        )
                    )
            for rows in (inflow_rows, outflow_rows, exch_rows, supply_rows, issuance_rows):
                await self._write("scalar", "whales.coinmetrics", rows)  # type: ignore[arg-type]

        chain_rows: dict[str, list[tuple[CanonicalObservation, str]]] = {
            m: []
            for m in (
                "coin_days_destroyed",
                "revived_supply_1y",
                "lth_spent_155d",
                "miner_origin_spent",
            )
        }
        for i in range(DAILY_DAYS):
            event = day_start(i)
            t = lat.trend[i]
            values = {
                "coin_days_destroyed": 6e6 * (1.0 + 0.5 * (1.0 - t) / 2.0 + 0.2 * _noise(rng)),
                "revived_supply_1y": 3_000.0 * (1.0 + 1.5 * max(0.0, t) + 0.3 * _noise(rng)),
                "lth_spent_155d": 15_000.0 * (1.0 + 0.8 * max(0.0, t) + 0.25 * _noise(rng)),
                "miner_origin_spent": 500.0 * (1.0 + 0.3 * _noise(rng)),
            }
            for metric, value in values.items():
                chain_rows[metric].append(
                    self._obs(
                        whale_dataset(metric, "BTC").dataset_id,
                        asset="BTC",
                        subject=network_ref("BTC"),
                        venue=None,
                        provider=blockchair.PROVIDER_ID,
                        original="blockchair",
                        event=event,
                        value=max(value, 1.0),
                    )
                )
        for rows in chain_rows.values():
            await self._write("scalar", "whales.blockchair_daily", rows)  # type: ignore[arg-type]

        # Rich-list balances: one snapshot per day at 06:00 UTC for every tracked address.
        balances = {
            EXCHANGE_WALLET: 250_000.0,
            GOVERNMENT_WALLET: 61_000.0,
            **dict.fromkeys(UNLABELLED_WALLETS, 10_000.0),
        }
        balance_rows: dict[str, list[tuple[CanonicalObservation, str]]] = {a: [] for a in balances}
        dataset_id = whale_dataset("address_balance", "BTC").dataset_id
        for i in range(DAILY_DAYS):
            event = day_start(i) + timedelta(hours=6)
            for address in balances:
                if address == EXCHANGE_WALLET:
                    balances[address] *= 1.0 - 0.0008 * lat.inst[i]
                elif address != GOVERNMENT_WALLET:
                    balances[address] *= 1.0 + 0.0006 * lat.trend[i] + 0.0002 * _noise(rng)
                balance_rows[address].append(
                    self._obs(
                        dataset_id,
                        asset="BTC",
                        subject=address_ref("bitcoin", address),
                        venue=None,
                        provider=blockchair.PROVIDER_ID,
                        original="blockchair",
                        event=event,
                        value=balances[address],
                    )
                )
        for rows in balance_rows.values():
            await self._write("scalar", "whales.address_balance", rows)  # type: ignore[arg-type]

        published = day_start(0).isoformat()
        label_lines = [",".join(CSV_COLUMNS)]
        for address, kind, entity, name in (
            (EXCHANGE_WALLET, "exchange", "synthetic-exchange", "Synthetic exchange"),
            (
                GOVERNMENT_WALLET,
                "government",
                "synthetic-government",
                "Synthetic government wallet",
            ),
        ):
            label_lines.append(
                f"bitcoin,{address},{kind},{entity},{name},attributed,0.6,"
                f'"Synthetic benchmark label",Synthetic labels,,,,{published}'
            )
        if self.engine is not None:
            await import_labels(self.engine, parse_label_csv("\n".join(label_lines)), day_start(0))
        for line in label_lines[1:]:
            self.col._digest.update(f"label|{line}\n".encode())

    async def retail(self) -> None:
        lat, rng = self.lat, random.Random(f"{SEED}:retail")
        for symbol, coin_id in TRENDING_COINS.items():
            rows: list[tuple[CanonicalObservation, str]] = []
            for i in range(DAILY_DAYS):
                for hour in (0, 6, 12, 18):
                    if rng.random() < 0.08 + 0.45 * lat.retail[i] * (
                        0.4 if symbol == "BTC" else 1.0
                    ):
                        rank = 1 + int(rng.random() * 7)
                        rows.append(
                            self._obs(
                                TRENDING.dataset_id,
                                asset=symbol,
                                subject=coin_ref(coin_id),
                                venue=None,
                                provider=coingecko.PROVIDER_ID,
                                original="coingecko",
                                event=day_start(i) + timedelta(hours=hour),
                                value=Decimal(rank),
                            )
                        )
            await self._write("scalar", "retail.trending", rows)  # type: ignore[arg-type]
        rows = []
        for i in range(DAILY_DAYS):
            rows.append(
                self._obs(
                    SMALL_OUTPUT_COUNT.dataset_id,
                    asset="BTC",
                    subject="NETWORK:BTC",
                    venue=None,
                    provider=blockchair.PROVIDER_ID,
                    original="blockchair",
                    event=day_start(i),
                    value=Decimal(int(350_000 * (1.0 + 0.5 * lat.retail[i] + 0.05 * _noise(rng)))),
                )
            )
        await self._write("scalar", "retail.small_outputs", rows)  # type: ignore[arg-type]

    async def liquidity(self) -> None:
        lat, rng = self.lat, random.Random(f"{SEED}:liquidity")
        usdt, usdc, other = 90e9, 35e9, 8e9
        rows: dict[str, list[tuple[CanonicalObservation, str]]] = {
            "USDT": [],
            "USDC": [],
            "TOTAL": [],
        }
        dataset_id = "liquidity.stablecoin_supply.1d"
        for i in range(DAILY_DAYS):
            usdt *= 1.0 + 0.0007 * lat.liquidity[i] + 0.0002 * _noise(rng)
            usdc *= 1.0 + 0.0009 * lat.liquidity[i] + 0.0003 * _noise(rng)
            other *= 1.0 + 0.0003 * lat.liquidity[i] + 0.0002 * _noise(rng)
            for name, value in (("USDT", usdt), ("USDC", usdc), ("TOTAL", usdt + usdc + other)):
                rows[name].append(
                    self._obs(
                        dataset_id,
                        asset=name,
                        subject=f"STABLECOIN:{name}",
                        venue="defillama",
                        provider=defillama.PROVIDER_ID,
                        original="defillama",
                        event=day_start(i),
                        value=_dec(value, 2),
                    )
                )
        for series in rows.values():
            await self._write("scalar", "liquidity.stablecoins", series)  # type: ignore[arg-type]

    async def macro(self) -> None:
        lat, rng = self.lat, random.Random(f"{SEED}:macro")
        n = DAILY_DAYS

        def walk(start: float, drift: Callable[[int], float], vol: float) -> list[float]:
            out, level = [], start
            for i in range(n):
                level *= 1.0 + drift(i) + vol * _noise(rng)
                out.append(level)
            return out

        sp = walk(4_500.0, lambda i: 0.0004 * lat.trend[i], 0.008)
        nq = walk(15_000.0, lambda i: 0.0005 * lat.trend[i], 0.011)
        series: dict[str, Callable[[int], float]] = {
            "macro.dxy_broad_proxy.1d": lambda i: 120.0 - 4.0 * lat.macro[i] + 0.3 * _noise(rng),
            "macro.ust_yield_2y.1d": lambda i: 4.0 + 0.8 * lat.macro[i] + 0.03 * _noise(rng),
            "macro.ust_yield_10y.1d": lambda i: 4.2 + 0.6 * lat.macro[i] + 0.03 * _noise(rng),
            "macro.fed_funds_effective.1d": lambda i: 4.33 - 0.5 * (i // 250) * 0.25,
            "macro.vix.1d": lambda i: max(9.0, 18.0 - 6.0 * lat.trend[i] + 1.5 * _noise(rng)),
            "macro.sp500.1d": lambda i: sp[i],
            "macro.nasdaq_composite.1d": lambda i: nq[i],
            "macro.oil_wti.1d": lambda i: 75.0 + 8.0 * lat.macro[i] + 0.8 * _noise(rng),
            "macro.reverse_repo.1d": lambda i: (
                800.0 + 600.0 * lat.liquidity[i] + 20.0 * _noise(rng)
            ),
            "macro.fed_balance_sheet.1w": lambda i: (
                7_500_000.0 - 400.0 * i * 0.2 + 5_000.0 * _noise(rng)
            ),
            "macro.treasury_general_account.1w": lambda i: (
                700_000.0 + 150_000.0 * lat.macro[i] + 5_000.0 * _noise(rng)
            ),
            "macro.m2_money_stock.1w": lambda i: 20_800.0 + 0.8 * i + 15.0 * _noise(rng),
            "macro.cpi.1mo": lambda i: 300.0 * (1.0 + 0.0025) ** (i / 30.0),
            "macro.pce_price_index.1mo": lambda i: 125.0 * (1.0 + 0.002) ** (i / 30.0),
            "macro.unemployment_rate.1mo": lambda i: 4.0 + 0.5 * lat.macro[i] + 0.05 * _noise(rng),
            "macro.m2_money_stock.1mo": lambda i: 20_700.0 + 0.8 * i,
        }
        for dataset_id, fn in series.items():
            spec = self.spec(dataset_id)
            rows: list[tuple[CanonicalObservation, str]] = []
            for i in range(n):
                day = FIRST_DAY + timedelta(days=i)
                if spec.period == "1d" and day.weekday() >= 5:
                    continue
                if spec.period == "1w" and day.weekday() != 2:
                    continue
                if spec.period == "1mo" and day.day != 1:
                    continue
                rows.append(
                    self._obs(
                        dataset_id,
                        asset="US",
                        subject="US",
                        venue=None,
                        provider=fred.PROVIDER_ID,
                        original="fred",
                        event=day_start(i),
                        value=fn(i),
                        places=4,
                    )
                )
            await self._write("scalar", "macro.fred", rows)  # type: ignore[arg-type]
        # Policy-rate target changes (sporadic events): an opening level, then three moves.
        for dataset_id, base in (
            ("macro.fed_funds_target_upper.event", 4.50),
            ("macro.fed_funds_target_lower.event", 4.25),
        ):
            rows = []
            for i, level in ((0, base), (260, base - 0.25), (520, base - 0.50), (780, base - 0.25)):
                rows.append(
                    self._obs(
                        dataset_id,
                        asset="US",
                        subject="US",
                        venue=None,
                        provider=fred.PROVIDER_ID,
                        original="fred",
                        event=day_start(i),
                        value=level,
                        places=2,
                    )
                )
            await self._write("scalar", "macro.fred_events", rows)  # type: ignore[arg-type]

    async def market(self) -> None:
        """Daily and hourly spot bars, daily/event market caps and the total market cap."""
        lat = self.lat
        daily_id = ohlcv_dataset("usd", "1d").dataset_id
        hourly_id = ohlcv_dataset("usd", "1h").dataset_id
        base_volume = {"BTC": 25_000.0, "ETH": 300_000.0, "SOL": 4e6, "XRP": 1.5e8}
        hours = self._hours()
        for asset in ASSETS:
            rng = random.Random(f"{SEED}:bars:{asset}")
            subject = coinbase.instrument_ref(coinbase.PRODUCTS[asset])
            px = lat.price[asset]
            daily: list[tuple[CanonicalBar, str]] = []
            for i in range(DAILY_DAYS):
                o = px[i - 1] if i else PRICE0[asset]
                c = px[i]
                hi = max(o, c) * (1.0 + 0.01 * rng.random())
                lo = min(o, c) * (1.0 - 0.01 * rng.random())
                vol = (
                    base_volume[asset]
                    * (1.0 + 10.0 * abs(c / o - 1.0))
                    * (0.8 + 0.4 * rng.random())
                )
                daily.append(
                    self._bar(
                        daily_id,
                        asset=asset,
                        subject=subject,
                        event=day_start(i),
                        o=o,
                        h=hi,
                        lo=lo,
                        c=c,
                        volume=vol,
                    )
                )
            await self._write("bar", "market.bars_1d", daily)  # type: ignore[arg-type]
            hourly: list[tuple[CanonicalBar, str]] = []
            for moment in hours:
                i = self._day_index(moment)
                o_day = px[i - 1] if i else PRICE0[asset]
                step = (px[i] - o_day) / 24.0
                h0 = moment.hour
                o = o_day + step * h0
                c = o_day + step * (h0 + 1) + o_day * 0.0015 * _noise(rng)
                hi = max(o, c) * (1.0 + 0.002 * rng.random())
                lo = min(o, c) * (1.0 - 0.002 * rng.random())
                vol = base_volume[asset] / 24.0 * (0.7 + 0.6 * rng.random())
                hourly.append(
                    self._bar(
                        hourly_id,
                        asset=asset,
                        subject=subject,
                        event=moment,
                        o=o,
                        h=hi,
                        lo=lo,
                        c=c,
                        volume=vol,
                    )
                )
            await self._write("bar", "market.bars_1h", hourly)  # type: ignore[arg-type]

        for asset in ASSETS:
            rng = random.Random(f"{SEED}:cap:{asset}")
            rows: list[tuple[CanonicalObservation, str]] = []
            for i in range(DAILY_DAYS + 1):
                price = lat.price[asset][min(i, DAILY_DAYS) - 1] if i else PRICE0[asset]
                rows.append(
                    self._obs(
                        MARKET_CAP_USD_1D.dataset_id,
                        asset=asset,
                        subject=asset,
                        venue=None,
                        provider=coingecko.PROVIDER_ID,
                        original="coingecko",
                        event=day_start(i),
                        value=_dec(price * SUPPLY[asset], 2),
                    )
                )
            await self._write("scalar", "market.market_cap_1d", rows)  # type: ignore[arg-type]
        for asset in ("BTC", "ETH"):
            rng = random.Random(f"{SEED}:capev:{asset}")
            rows = []
            for moment in hours:
                i = self._day_index(moment)
                price = lat.price[asset][i - 1] if i else PRICE0[asset]
                rows.append(
                    self._obs(
                        MARKET_CAP_USD.dataset_id,
                        asset=asset,
                        subject=asset,
                        venue=None,
                        provider=coingecko.PROVIDER_ID,
                        original="coingecko",
                        event=moment + timedelta(minutes=5),
                        value=_dec(price * SUPPLY[asset] * (1.0 + 0.002 * _noise(rng)), 2),
                    )
                )
            await self._write("scalar", "market.market_cap_event", rows)  # type: ignore[arg-type]
        rows = []
        rng = random.Random(f"{SEED}:totalcap")
        for moment in hours[::4]:
            i = self._day_index(moment)
            btc_cap = (lat.price["BTC"][i - 1] if i else PRICE0["BTC"]) * SUPPLY["BTC"]
            total = btc_cap / (0.55 + 0.05 * (0.5 - lat.retail[i])) * (1.0 + 0.002 * _noise(rng))
            rows.append(
                self._obs(
                    TOTAL_MARKET_CAP_USD.dataset_id,
                    asset="GLOBAL",
                    subject="GLOBAL",
                    venue=None,
                    provider=coingecko.PROVIDER_ID,
                    original="coingecko",
                    event=moment + timedelta(minutes=5),
                    value=_dec(total, 2),
                )
            )
        await self._write("scalar", "market_structure.total_market_cap", rows)  # type: ignore[arg-type]

    async def derivatives(self) -> None:
        lat = self.lat
        hours = self._hours()
        slow_hours = self._hours(max(self.hourly_days, SLOW_HOURLY_DAYS))
        venues = (
            ("binance", binance_futures.PROVIDER_ID, 1.0, 0.0),
            ("okx", okx_derivatives.PROVIDER_ID, 0.45, 0.00002),
        )
        for asset in PERP_ASSETS:
            rng = random.Random(f"{SEED}:deriv:{asset}")
            a = asset.lower()
            for venue, provider, oi_scale, funding_shift in venues:
                oi_rows: list[tuple[CanonicalObservation, str]] = []
                ls_rows: list[tuple[CanonicalObservation, str]] = []
                fund_rows: list[tuple[CanonicalObservation, str]] = []
                for moment in hours:
                    i = self._day_index(moment)
                    lev = lat.lev[i]
                    oi_rows.append(
                        self._obs(
                            derivatives_dataset("open_interest", asset).dataset_id,
                            asset=asset,
                            subject=perp_ref(asset),
                            venue=venue,
                            provider=provider,
                            original=venue,
                            event=moment,
                            value=OI_BASE[asset]
                            * oi_scale
                            * (0.5 + 0.9 * lev)
                            * (1.0 + 0.01 * _noise(rng)),
                            places=4,
                        )
                    )
                    ratio = (
                        0.9 + 0.8 * lat.retail[i]
                        if venue == "binance"
                        else 0.85 + 0.9 * lat.retail[i]
                    ) + 0.05 * _noise(rng)
                    ls_rows.append(
                        self._obs(
                            derivatives_dataset("long_short_account_ratio", asset).dataset_id,
                            asset=asset,
                            subject=perp_ref(asset) if venue == "binance" else contracts_ref(asset),
                            venue=venue,
                            provider=provider,
                            original=venue,
                            event=moment,
                            value=max(ratio, 0.2),
                            places=6,
                        )
                    )
                for moment in slow_hours:
                    if moment.hour % 8 == 0:
                        lev = lat.lev[self._day_index(moment)]
                        fund_rows.append(
                            self._obs(
                                derivatives_dataset("funding_rate", asset).dataset_id,
                                asset=asset,
                                subject=perp_ref(asset),
                                venue=venue,
                                provider=provider,
                                original=venue,
                                event=moment,
                                value=0.0001
                                + 0.0006 * (lev - 0.5)
                                + funding_shift
                                + 0.00005 * _noise(rng),
                                places=8,
                            )
                        )
                await self._write("scalar", "derivatives.open_interest", oi_rows)  # type: ignore[arg-type]
                await self._write("scalar", "derivatives.long_short_ratio", ls_rows)  # type: ignore[arg-type]
                await self._write("scalar", "derivatives.funding", fund_rows)  # type: ignore[arg-type]
            liq_ds = derivatives_dataset("liquidations", asset).dataset_id
            for side in ("long", "short"):
                liq_rows: list[tuple[CanonicalObservation, str]] = []
                for moment in hours:
                    i = self._day_index(moment)
                    bias = 1.0 + 0.8 * (-lat.trend[i] if side == "long" else lat.trend[i])
                    if rng.random() < 0.02 + 0.05 * lat.lev[i]:
                        amount = (
                            OI_BASE[asset] * 0.002 * (1.0 + 3.0 * rng.random()) * max(bias, 0.2)
                        )
                    else:
                        amount = OI_BASE[asset] * 0.0001 * rng.random()
                    liq_rows.append(
                        self._obs(
                            liq_ds,
                            asset=asset,
                            subject=liquidation_ref(asset, side),
                            venue="okx",
                            provider=okx_derivatives.PROVIDER_ID,
                            original="okx",
                            event=moment,
                            value=amount,
                            places=4,
                        )
                    )
                await self._write("scalar", "derivatives.liquidations", liq_rows)  # type: ignore[arg-type]
            del a
        for asset, shift in (("BTC", 0.0), ("ETH", 0.08)):
            rng = random.Random(f"{SEED}:dvol:{asset}")
            rows: list[tuple[CanonicalObservation, str]] = []
            for moment in slow_hours:
                i = self._day_index(moment)
                rows.append(
                    self._obs(
                        derivatives_dataset("volatility_index", asset).dataset_id,
                        asset=asset,
                        subject=dvol_ref(asset),
                        venue="deribit",
                        provider=deribit.PROVIDER_ID,
                        original="deribit",
                        event=moment,
                        value=max(0.2, 0.5 - 0.15 * lat.trend[i] + shift + 0.02 * _noise(rng)),
                        places=6,
                    )
                )
            await self._write("scalar", "derivatives.dvol", rows)  # type: ignore[arg-type]

    FAMILIES = ("institutional", "whales", "retail", "liquidity", "macro", "market", "derivatives")

    async def run(self, only: Sequence[str] | None = None) -> SeedSummary:
        await self.register_all()
        for name in self.FAMILIES:
            if only is None or name in only:
                await getattr(self, name)()
        return SeedSummary(
            seed=SEED,
            seed_version=SEED_VERSION,
            hourly_days=self.hourly_days,
            anchor=ANCHOR,
            first_day=FIRST_DAY,
            daily_days=DAILY_DAYS,
            analysis_days=ANALYSIS_DAYS,
            fingerprint=self.col.hexdigest(),
            table_counts=dict(self.col.counts),
            family_counts=dict(self.col.families),
            series_count=self.series,
            notes=[f"records after the anchor, not written: {self.col.dropped_after_anchor}"],
        )


async def dry_run(hourly_days: int = DEFAULT_HOURLY_DAYS) -> SeedSummary:
    """Generate and fingerprint the whole history without any database."""
    return await Seeder(hourly_days=hourly_days).run()


async def seed_database(
    engine: AsyncEngine, raw_dir: object, hourly_days: int = DEFAULT_HOURLY_DAYS
) -> SeedSummary:
    """Write the whole synthetic history through the platform's own stores and return its
    fingerprint and counts. The caller is responsible for having verified that ``engine`` points
    at the disposable database (this module never decides that)."""
    return await Seeder(engine, raw_dir, hourly_days).run()


async def stored_counts(engine: AsyncEngine) -> dict[str, int]:
    """Row counts of the three observation tables, read back from the database."""
    out: dict[str, int] = {}
    async with engine.connect() as conn:
        for table in ("obs.observation", "obs.market_bar", "obs.institutional_flow"):
            query = text(f"SELECT count(*) FROM {table}")  # noqa: S608 — constant table names
            out[table] = int((await conn.execute(query)).scalar_one())
    return out
