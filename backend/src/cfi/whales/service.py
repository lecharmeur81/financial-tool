"""Whale intelligence read service: on-chain flows, holders, large transfers, labels, the Whale
Flow Score and contradiction indicators.

Every metric carries the shared envelope (source, timestamp, unit, calculation, freshness, data
quality, evidence category and — for actor data — evidence class). Every address carries its
classification with evidence, source and confidence. Nothing here is a signal, forecast or
recommendation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.addresses import InvalidAddressError, canonical_address
from cfi.core.errors import NotFoundError
from cfi.core.time import ensure_utc
from cfi.domain.datasets import DatasetSpec
from cfi.institutional.score import ComponentResult, ScoreResult
from cfi.institutional.service import (
    Freshness,
    InstitutionalService,
    age_freshness,
    num,
    quality_summary,
)
from cfi.market.universe import ASSET_SYMBOLS
from cfi.providers import blockchair, coinmetrics
from cfi.whales import score as ws
from cfi.whales.label_store import load_entities, load_labels
from cfi.whales.labels import (
    CLASS_LABELS,
    KNOWN_CLASSES,
    UNKNOWN_LARGE,
    Classification,
    Entity,
    Label,
    classify,
)
from cfi.whales.queries import WhaleQueries
from cfi.whales.sources import ADAPTERS, ATTRIBUTION, SOURCES, provider_for
from cfi.whales.universe import (
    CHAIN_OF,
    DORMANCY_ASSETS,
    LARGE_HOLDER_MIN,
    LARGE_TRANSFER_MIN,
    RICH_LIST_SIZE,
    WHALE_ASSETS,
    all_datasets,
    dataset,
    has_dataset,
)

DEFAULT_RANGE = timedelta(days=90)
MAX_RANGE = timedelta(days=5 * 366)
# Reads for the score: 97 days of coin-age data plus slack.
SCORE_LOOKBACK = timedelta(days=110)
# Publication lag after a UTC day closes, plus one scheduled run of slack (hours).
DUE_LAG: dict[str, timedelta] = {
    coinmetrics.PROVIDER_ID: timedelta(hours=12),
    blockchair.PROVIDER_ID: timedelta(hours=16),
}
SNAPSHOT_STALE_AFTER = timedelta(hours=36)
TRANSFER_RANGE = timedelta(days=7)
TRANSFER_LIST_LIMIT = 200

DAILY_METRICS: tuple[str, ...] = (
    "exchange_inflow",
    "exchange_outflow",
    "exchange_supply",
    "supply",
    "issuance",
    "coin_days_destroyed",
    "revived_supply_1y",
    "lth_spent_155d",
    "miner_origin_spent",
)
LABELS: dict[str, str] = {
    "exchange_inflow": "Exchange inflow",
    "exchange_outflow": "Exchange outflow",
    "exchange_supply": "Exchange supply",
    "supply": "Current supply",
    "issuance": "New issuance",
    "coin_days_destroyed": "Coin days destroyed",
    "revived_supply_1y": "Coins ≥ 1 year old moved",
    "lth_spent_155d": "Coins ≥ 155 days old moved",
    "miner_origin_spent": "Newly mined (coinbase) coins moved",
}
EVIDENCE: dict[str, str | None] = {
    "exchange_inflow": "attributed",
    "exchange_outflow": "attributed",
    "exchange_supply": "attributed",
}

INTERPRETATION_LIMITS = [
    "Exchange flows rely on Coin Metrics' attribution of exchange addresses (attributed "
    "evidence); unattributed exchange wallets are not included.",
    "An address is not an owner: one entity can use many addresses, and one address (e.g. a "
    "custodian's) can hold coins of many owners. 'Unknown large holder' means a large unlabelled "
    "address — never an institution (R5).",
    "Coin age says when coins last moved, not who moved them or why; moving coins are not "
    "necessarily sold.",
    "Coinbase-origin spending shows newly mined coins moving (typically pool payouts), not "
    "miner selling.",
    "The score describes recent on-chain behaviour; it is not a forecast, a signal to act, or "
    "investment advice.",
]

NOT_TRACKED = [
    {
        "item": "Stock of dormant / long-term-holder supply (e.g. supply last active ≥ 1 year)",
        "reason": "not in the Coin Metrics Community catalogue; only coins moving (flows) are "
        "measured, from Blockchair",
    },
    {
        "item": "Flows between miners and exchanges",
        "reason": "needs a miner address attribution; no verified free source",
    },
    {
        "item": "Whale data for SOL and XRP",
        "reason": "no verified free source for exchange flows, rich lists or transfers",
    },
    {
        "item": "Labelled Ethereum addresses",
        "reason": "no free label source could be read (the checked page returned an error); "
        "Ethereum addresses are classified by size only",
    },
    {
        "item": "Real-time transfer alerts (e.g. Whale Alert)",
        "reason": "paid API only",
    },
    {
        "item": "Balance bands (number of addresses holding 1-10, 10-100 … coins)",
        "reason": "not in the free Coin Metrics catalogue",
    },
]


def _day_start(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _pct(value: Decimal | None) -> str | None:
    return None if value is None else format(value.quantize(Decimal("0.0001")), "f")


def daily_freshness(latest: date | None, due: date, rule: str) -> Freshness:
    if latest is None:
        return Freshness("no_data", None, due, None, rule, "no data stored")
    if latest >= due:
        return Freshness("fresh", latest, due, None, rule, "up to date")
    return Freshness(
        "stale", latest, due, None, rule, f"newest stored day {latest} is older than {due}"
    )


def to_series(rows: Sequence[dict[str, Any]]) -> dict[date, ws.DayValue]:
    return {
        r["event_time"].date(): ws.DayValue(
            day=r["event_time"].date(),
            value=r["value"],
            quality_status=r["quality_status"],
            revision=r["revision"],
            pit_reliability=r["pit_reliability"],
            available_at_estimated=r["available_at_estimated"],
        )
        for r in rows
    }


def to_snapshots(
    rows: Sequence[dict[str, Any]],
    classes: dict[str, Classification],
) -> list[ws.Snapshot]:
    """Group balance rows by snapshot time; each address gets its class for that snapshot."""
    grouped: dict[datetime, dict[str, Decimal]] = defaultdict(dict)
    for r in rows:
        if r["value"] is None:
            continue
        address = r["subject_ref"].split(":", 1)[1]
        grouped[r["event_time"]][address] = r["value"]
    return [
        ws.Snapshot(
            time=t,
            balances=balances,
            classes={
                a: classes[f"{t.isoformat()}|{a}"].actor_class
                for a in balances
                if f"{t.isoformat()}|{a}" in classes
            },
        )
        for t, balances in sorted(grouped.items())
    ]


@dataclass
class _Context:
    as_of: datetime
    knowledge_time: datetime
    labels: list[Label] = field(default_factory=list)
    entities: dict[str, Entity] = field(default_factory=dict)


@dataclass
class WhaleService:
    queries: WhaleQueries
    enabled_providers: list[str] = field(default_factory=list)
    institutional: InstitutionalService | None = None

    # ------------------------------------------------------------------ helpers

    def source(self, spec: DatasetSpec) -> dict[str, Any]:
        provider_id = provider_for(spec.dataset_id)
        assert provider_id is not None  # noqa: S101 — every whale dataset has a source
        caps = ADAPTERS[provider_id].capabilities
        return {
            "provider_id": provider_id,
            "provider_name": caps.display_name,
            "original_source": caps.original_source,
            "dataset_id": spec.dataset_id,
            "enabled": provider_id in self.enabled_providers,
            "terms_verified": caps.terms_verified,
            "attribution": ATTRIBUTION.get(provider_id),
        }

    @staticmethod
    def _asset(asset: str, allowed: tuple[str, ...] = WHALE_ASSETS) -> str:
        if asset not in ASSET_SYMBOLS:
            raise NotFoundError(f"Unknown asset '{asset}'.")
        if asset not in allowed:
            raise NotFoundError(
                f"No whale data is tracked for {asset} (tracked: {', '.join(allowed)})."
            )
        return asset

    @staticmethod
    def _range(start: date | None, end: date | None, as_of: datetime) -> tuple[date, date]:
        last = ensure_utc(as_of).date() + timedelta(days=1)
        end = last if end is None else min(end, last)
        if start is None:
            start = end - DEFAULT_RANGE
        start = max(start, end - MAX_RANGE)
        if start >= end:
            raise NotFoundError("Empty date range.")
        return start, end

    def _due(self, spec: DatasetSpec, as_of: datetime) -> date:
        provider = provider_for(spec.dataset_id) or coinmetrics.PROVIDER_ID
        return ws.due_day(as_of, DUE_LAG[provider])

    async def _context(self, as_of: datetime, knowledge_time: datetime, chain: str) -> _Context:
        ctx = _Context(as_of, knowledge_time)
        ctx.labels = await load_labels(self.queries.engine, chain=chain)
        ctx.entities = await load_entities(self.queries.engine)
        return ctx

    @staticmethod
    def _classification(c: Classification) -> dict[str, Any]:
        return {
            "address": c.address,
            "chain": c.chain,
            "actor_class": c.actor_class,
            "display": c.display,
            "entity_id": c.entity_id,
            "entity_name": c.entity_name,
            "evidence_class": c.evidence_class,
            "confidence": num(c.confidence),
            "evidence": c.evidence,
            "source": c.source,
            "source_url": c.source_url,
            "rule": c.rule,
            "conflicting_labels": [
                {
                    "actor_class": lb.actor_class,
                    "entity_id": lb.entity_id,
                    "evidence_class": str(lb.evidence_class),
                    "confidence": num(lb.confidence),
                    "source": lb.source,
                }
                for lb in c.conflicts
            ],
        }

    def _classify(
        self,
        ctx: _Context,
        chain: str,
        address: str | None,
        at: datetime,
        balance: Decimal | None = None,
    ) -> Classification | None:
        if address is None:
            return None
        asset = next(a for a, c in CHAIN_OF.items() if c == chain)
        try:
            return classify(
                chain,
                address,
                ctx.labels,
                at=at,
                as_of=ctx.as_of,
                knowledge_time=ctx.knowledge_time,
                entities=ctx.entities,
                balance=balance,
                large_holder_min=LARGE_HOLDER_MIN[asset],
                unit=asset,
            )
        except InvalidAddressError:
            return None

    async def _daily(
        self, metric: str, asset: str, start: date, end: date, as_of: datetime, kt: datetime
    ) -> dict[date, ws.DayValue]:
        if not has_dataset(metric, asset):
            return {}
        rows = await self.queries.observations(
            dataset(metric, asset).dataset_id,
            asset=asset,
            start=_day_start(start),
            end=_day_start(end),
            as_of=as_of,
            knowledge_time=kt,
        )
        return to_series(rows)

    async def _last_run(self, spec: DatasetSpec, asset: str) -> Any:
        provider = provider_for(spec.dataset_id)
        return await self.queries.last_job(spec.dataset_id, provider or "", asset)

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        return {
            "assets": list(WHALE_ASSETS),
            "coin_age_assets": list(DORMANCY_ASSETS),
            "thresholds": {
                "large_transfer": {a: num(v) for a, v in LARGE_TRANSFER_MIN.items()},
                "unknown_large_holder_balance": {a: num(v) for a, v in LARGE_HOLDER_MIN.items()},
                "rich_list_size": RICH_LIST_SIZE,
                "note": "judgment parameters chosen by design, not fitted to data",
            },
            "classes": [
                {"actor_class": c, "label": CLASS_LABELS[c]}
                for c in (*KNOWN_CLASSES, UNKNOWN_LARGE)
            ],
            "classification_rules": [
                "A known class (exchange, institution, fund, market maker, protocol, miner, "
                "government, other) needs a label from a named source, with evidence and "
                "confidence.",
                "Institution, fund and market maker labels need direct or attributed evidence; "
                "the database rejects inferred ones.",
                "Size alone only ever gives 'unknown large holder' (inferred).",
                "Labels count from their publication time (available_at) and within their "
                "validity period (valid_from / valid_to).",
                "When labels disagree, the best-evidenced one is shown and the others are listed "
                "as conflicts.",
            ],
            "datasets": [
                {
                    "dataset_id": d.dataset_id,
                    "description": d.description,
                    "unit": d.unit,
                    "availability_rule": d.availability.as_dict(),
                    "providers": [s.provider_id for s in SOURCES if s.dataset == d],
                }
                for d in all_datasets()
            ],
            "providers": [
                {
                    "provider_id": pid,
                    "display_name": a.capabilities.display_name,
                    "enabled": pid in self.enabled_providers,
                    "terms_verified": a.capabilities.terms_verified,
                    "notes": a.capabilities.notes,
                    "attribution": ATTRIBUTION.get(pid),
                }
                for pid, a in ADAPTERS.items()
            ],
            "schedule": [
                {
                    "provider_id": s.provider_id,
                    "dataset_id": s.dataset.dataset_id,
                    "subject": s.subject,
                    "every_hours": s.interval_seconds / 3600,
                    "history_days": s.history_days,
                }
                for s in SOURCES
            ],
            "score": score_definition(),
            "not_tracked": NOT_TRACKED,
        }

    # ------------------------------------------------------------------ flows

    async def flows(
        self,
        *,
        asset: str,
        start: date | None,
        end: date | None,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        asset = self._asset(asset)
        start, end = self._range(start, end, as_of)
        series: dict[str, dict[date, ws.DayValue]] = {}
        datasets = []
        for metric in DAILY_METRICS:
            if not has_dataset(metric, asset):
                continue
            spec = dataset(metric, asset)
            data = await self._daily(metric, asset, start, end, as_of, knowledge_time)
            series[metric] = data
            latest = await self.queries.latest_observation(
                spec.dataset_id, asset=asset, as_of=as_of, knowledge_time=knowledge_time
            )
            due = self._due(spec, as_of)
            present = [v for v in data.values() if v.has_value]
            datasets.append(
                {
                    "metric": metric,
                    "label": LABELS[metric],
                    "dataset_id": spec.dataset_id,
                    "unit": spec.unit,
                    "evidence_class": EVIDENCE.get(metric),
                    "description": spec.description,
                    "source": self.source(spec),
                    "freshness": daily_freshness(
                        latest["event_time"].date() if latest else None,
                        due,
                        f"newest day ≥ latest day due ({DUE_LAG[self.source(spec)['provider_id']]} "
                        "after the day closes)",
                    ).as_dict(),
                    "quality": quality_summary(
                        status="ok" if present else "missing",
                        notes=[],
                        days_present=len(present),
                        flagged=sum(v.quality_status in ws.FLAGGED for v in present),
                        revised=sum(v.revision > 0 for v in present),
                        backfilled=sum(v.pit_reliability == "backfilled_latest" for v in present),
                        estimated_availability=sum(
                            v.quality_status == "estimated" for v in present
                        ),
                    ),
                    "last_run": await self._last_run(spec, asset),
                }
            )
        days_out = []
        day = start
        while day < end:
            values: dict[str, Any] = {}
            for metric, data in series.items():
                v = data.get(day)
                values[metric] = (
                    None
                    if v is None
                    else {
                        "value": num(v.value),
                        "quality_status": v.quality_status,
                        "revision": v.revision,
                        "pit_reliability": v.pit_reliability,
                    }
                )
            inflow, outflow = (
                series["exchange_inflow"].get(day),
                series["exchange_outflow"].get(day),
            )
            netflow = (
                inflow.value - outflow.value
                if inflow and outflow and inflow.value is not None and outflow.value is not None
                else None
            )
            if any(values.values()):
                days_out.append({"date": day, "values": values, "netflow": num(netflow)})
            day += timedelta(days=1)
        return {
            "asset": asset,
            "unit": asset.lower(),
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "range": {"start": start, "end": end},
            "evidence_category": "observed",
            "definitions": {
                "netflow": "exchange inflow − exchange outflow for the day (calculated; positive "
                "= coins moving onto exchanges)",
                "event_time": "UTC day (00:00 label = the day the value covers)",
            },
            "datasets": datasets,
            "days": days_out,
            "interpretation_limits": INTERPRETATION_LIMITS,
        }

    # ------------------------------------------------------------------ holders

    async def _snapshots(
        self, asset: str, ctx: _Context
    ) -> tuple[list[ws.Snapshot], dict[str, Classification]]:
        spec = dataset("address_balance", asset)
        rows = await self.queries.observations(
            spec.dataset_id,
            asset=asset,
            start=ctx.as_of - ws.SNAPSHOT_GAP - timedelta(days=2),
            end=ctx.as_of + timedelta(seconds=1),
            as_of=ctx.as_of,
            knowledge_time=ctx.knowledge_time,
        )
        chain = CHAIN_OF[asset]
        classes: dict[str, Classification] = {}
        for r in rows:
            if r["value"] is None:
                continue
            address = r["subject_ref"].split(":", 1)[1]
            c = self._classify(ctx, chain, address, r["event_time"], r["value"])
            if c is not None:
                classes[f"{r['event_time'].isoformat()}|{address}"] = c
        return to_snapshots(rows, classes), classes

    async def holders(
        self, *, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        asset = self._asset(asset)
        chain = CHAIN_OF[asset]
        ctx = await self._context(as_of, knowledge_time, chain)
        snapshots, classes = await self._snapshots(asset, ctx)
        now, then = ws.pick_snapshots(snapshots, as_of)
        spec = dataset("address_balance", asset)
        rows = []
        cohorts: list[dict[str, Any]] = []
        if now is not None:
            ordered = sorted(now.balances.items(), key=lambda kv: kv[1], reverse=True)
            for rank, (address, balance) in enumerate(ordered, start=1):
                c = classes[f"{now.time.isoformat()}|{address}"]
                before = then.balances.get(address) if then else None
                rows.append(
                    {
                        "rank": rank,
                        "balance": num(balance),
                        "change_7d": num(balance - before) if before is not None else None,
                        "change_7d_note": None
                        if then is None or before is not None
                        else "not in the top 100 seven days earlier",
                        "classification": self._classification(c),
                    }
                )
            for actor_class in (*KNOWN_CLASSES, UNKNOWN_LARGE):
                members = [a for a, k in now.classes.items() if k == actor_class]
                if not members:
                    continue
                total = sum((now.balances[a] for a in members), Decimal(0))
                change = ws.holder_change(now, then, actor_class) if then else None
                cohorts.append(
                    {
                        "actor_class": actor_class,
                        "label": CLASS_LABELS[actor_class],
                        "addresses": len(members),
                        "balance": num(total),
                        "change_7d": num(change.change) if change else None,
                        "change_7d_pct": _pct(change.change_pct) if change else None,
                        "change_7d_addresses_compared": change.matched if change else None,
                        "change_7d_addresses_left": change.left if change else None,
                        "calculation": (
                            "Σ balance change of the addresses of this class in both snapshots "
                            "(class taken from the earlier snapshot)"
                        ),
                    }
                )
        latest_time = now.time if now else None
        return {
            "asset": asset,
            "unit": asset.lower(),
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "evidence_category": "observed",
            "snapshot": latest_time,
            "compared_with": then.time if then else None,
            "compared_note": None
            if then
            else "no snapshot 7 days (± 1 day) earlier: changes need a week of daily snapshots",
            "definition": spec.description,
            "source": self.source(spec),
            "label_sources": sorted({lb.source for lb in ctx.labels}),
            "freshness": age_freshness(
                latest_time, SNAPSHOT_STALE_AFTER, as_of, "newest snapshot"
            ).as_dict(),
            "holders": rows,
            "cohorts": cohorts,
            "last_run": await self._last_run(spec, asset),
            "interpretation_limits": INTERPRETATION_LIMITS,
        }

    # ------------------------------------------------------------------ transfers

    async def transfers(
        self,
        *,
        asset: str,
        start: datetime | None,
        end: datetime | None,
        as_of: datetime,
        knowledge_time: datetime,
        limit: int = TRANSFER_LIST_LIMIT,
    ) -> dict[str, Any]:
        asset = self._asset(asset)
        chain = CHAIN_OF[asset]
        spec = dataset("large_transfer", asset)
        end = as_of if end is None else min(ensure_utc(end), as_of)
        start = end - TRANSFER_RANGE if start is None else ensure_utc(start)
        if start >= end:
            raise NotFoundError("Empty time range.")
        if end - start > timedelta(days=31):
            raise NotFoundError("Transfer range is limited to 31 days.")
        ctx = await self._context(as_of, knowledge_time, chain)
        rows = await self.queries.transfers(
            spec.dataset_id,
            asset=asset,
            start=start,
            end=end,
            as_of=as_of,
            knowledge_time=knowledge_time,
            min_value=LARGE_TRANSFER_MIN[asset],
        )
        # Addresses in the latest top-100 snapshot are classified with that balance (size rule);
        # other addresses have no known balance and are only classified by labels.
        snapshots, _ = await self._snapshots(asset, ctx)
        latest_balances = snapshots[-1].balances if snapshots else {}
        items: list[dict[str, Any]] = []
        summary: dict[str, Decimal] = defaultdict(Decimal)
        counts: dict[str, int] = defaultdict(int)
        for r in rows:
            sender = self._classify(
                ctx, chain, r["sender"], r["event_time"], latest_balances.get(r["sender"] or "")
            )
            recipient = self._classify(
                ctx,
                chain,
                r["recipient"],
                r["event_time"],
                latest_balances.get(r["recipient"] or ""),
            )
            value: Decimal = r["value_native"]
            to_ex = recipient is not None and recipient.actor_class == "exchange"
            from_ex = sender is not None and sender.actor_class == "exchange"
            key = (
                "exchange_to_exchange"
                if to_ex and from_ex
                else "to_exchange"
                if to_ex
                else "from_exchange"
                if from_ex
                else "other"
            )
            summary[key] += value
            counts[key] += 1
            if len(items) < limit:
                items.append(
                    {
                        "time": r["event_time"],
                        "tx_hash": r["tx_hash"],
                        "output_index": r["output_index"],
                        "block_height": r["block_height"],
                        "value": num(value),
                        "value_usd": num(r["value_usd"]),
                        "direction": key,
                        "sender": self._classification(sender) if sender else None,
                        "recipient": self._classification(recipient) if recipient else None,
                        "quality_status": r["quality_status"],
                        "quality_note": r["quality_note"],
                        "available_at": r["available_at"],
                        "pit_reliability": r["pit_reliability"],
                    }
                )
        total = sum(summary.values(), Decimal(0))
        return {
            "asset": asset,
            "unit": asset.lower(),
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "range": {"start": start, "end": end},
            "evidence_category": "observed",
            "threshold": num(LARGE_TRANSFER_MIN[asset]),
            "definition": spec.description,
            "source": self.source(spec),
            "summary": {
                "transfers": len(rows),
                "total": num(total),
                "by_direction": [
                    {"direction": k, "transfers": counts[k], "total": num(summary[k])}
                    for k in ("to_exchange", "from_exchange", "exchange_to_exchange", "other")
                ],
                "note": (
                    "Directions use labelled exchange addresses only; unlabelled exchange wallets "
                    "count as 'other'."
                    + (
                        " Bitcoin outputs have no sender, so 'from exchange' cannot be seen."
                        if chain == "bitcoin"
                        else ""
                    )
                ),
            },
            "transfers": items,
            "truncated": len(rows) > limit,
            "last_run": await self._last_run(spec, asset),
            "interpretation_limits": INTERPRETATION_LIMITS,
        }

    # ------------------------------------------------------------------ labels

    async def address(
        self, *, chain: str, address: str, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        if chain not in CHAIN_OF.values():
            raise NotFoundError(f"Unsupported chain '{chain}'.")
        try:
            canonical = canonical_address(chain, address)
        except InvalidAddressError as exc:
            raise NotFoundError(f"Not a valid {chain} address: {exc}") from exc
        ctx = await self._context(as_of, knowledge_time, chain)
        asset = next(a for a, c in CHAIN_OF.items() if c == chain)
        latest = await self.queries.latest_observation_for(
            dataset("address_balance", asset).dataset_id,
            subject_ref=f"{chain}:{canonical}",
            as_of=as_of,
            knowledge_time=knowledge_time,
        )
        balance = latest["value"] if latest else None
        c = self._classify(ctx, chain, canonical, as_of, balance)
        assert c is not None  # noqa: S101 — validated above
        labels = [lb for lb in ctx.labels if lb.address == canonical]
        return {
            "chain": chain,
            "address": canonical,
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "classification": self._classification(c),
            "balance": {
                "value": num(balance),
                "unit": asset.lower(),
                "snapshot": latest["event_time"] if latest else None,
                "note": None if latest else "not in any stored top-100 snapshot",
            },
            "labels": [
                {
                    "label_id": lb.label_id,
                    "actor_class": lb.actor_class,
                    "entity_id": lb.entity_id,
                    "entity_name": ctx.entities[lb.entity_id].name
                    if lb.entity_id in ctx.entities
                    else None,
                    "evidence_class": str(lb.evidence_class),
                    "confidence": num(lb.confidence),
                    "evidence": lb.evidence,
                    "source": lb.source,
                    "source_url": lb.source_url,
                    "valid_from": lb.valid_from,
                    "valid_to": lb.valid_to,
                    "available_at": lb.available_at,
                    "recorded_at": lb.recorded_at,
                    "counts_now": lb.counts(as_of, as_of, knowledge_time),
                }
                for lb in labels
            ],
        }

    async def entities(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        labels = await load_labels(self.queries.engine)
        ents = await load_entities(self.queries.engine)
        per: dict[str, list[Label]] = defaultdict(list)
        for lb in labels:
            if lb.entity_id and lb.counts(as_of, as_of, knowledge_time):
                per[lb.entity_id].append(lb)
        return {
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "entities": [
                {
                    "entity_id": e.entity_id,
                    "name": e.name,
                    "actor_class": e.actor_class,
                    "class_label": CLASS_LABELS[e.actor_class],
                    "addresses": [
                        {
                            "chain": lb.chain,
                            "address": lb.address,
                            "evidence_class": str(lb.evidence_class),
                            "confidence": num(lb.confidence),
                            "source": lb.source,
                        }
                        for lb in per.get(e.entity_id, [])
                    ],
                }
                for e in sorted(ents.values(), key=lambda e: (e.actor_class, e.name))
            ],
            "sources": sorted({lb.source for lb in labels}),
        }

    # ------------------------------------------------------------------ score

    async def _score(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> tuple[ScoreResult, ws.HolderChange | None, dict[str, Any]]:
        as_of_day = ensure_utc(as_of).date()
        start, end = as_of_day - SCORE_LOOKBACK, as_of_day + timedelta(days=1)
        inflow = await self._daily("exchange_inflow", asset, start, end, as_of, knowledge_time)
        outflow = await self._daily("exchange_outflow", asset, start, end, as_of, knowledge_time)
        supply = await self._daily("exchange_supply", asset, start, end, as_of, knowledge_time)
        revived = await self._daily("revived_supply_1y", asset, start, end, as_of, knowledge_time)
        ctx = await self._context(as_of, knowledge_time, CHAIN_OF[asset])
        snapshots, _ = await self._snapshots(asset, ctx)
        due = ws.due_day(as_of, DUE_LAG[coinmetrics.PROVIDER_ID])
        window_end = ws.window_end([inflow, outflow, supply], due, as_of)
        result, change = ws.compute_score(
            ws.ScoreInputs(
                asset=asset,
                unit=asset.lower(),
                as_of=as_of,
                end=window_end,
                inflow=inflow,
                outflow=outflow,
                exchange_supply=supply,
                revived=revived,
                snapshots=snapshots,
            )
        )
        # Revived coins come from another provider with its own lag: its window ends at its own
        # last due day (never later than the exchange window).
        if asset in DORMANCY_ASSETS:
            revived_end = min(
                window_end,
                ws.window_end([revived], ws.due_day(as_of, DUE_LAG[blockchair.PROVIDER_ID]), as_of),
            )
            if revived_end != window_end:
                result.components[3] = ws.revived_component(revived, revived_end, asset)
                result = ws.combine(asset, as_of, result.components)
        spent = await self._daily("miner_origin_spent", asset, start, end, as_of, knowledge_time)
        issuance = await self._daily("issuance", asset, start, end, as_of, knowledge_time)
        context = {
            "knowledge_time": knowledge_time,
            "window_end": window_end,
            "due": due,
            "supply": supply,
            "snapshots": snapshots,
            "miner": ws.miner_spending_ratio(spent, issuance, window_end)
            if asset in DORMANCY_ASSETS
            else None,
            "freshness": {
                m: daily_freshness(
                    max((d for d, v in s.items() if v.has_value), default=None),
                    self._due(dataset(m, asset), as_of),
                    "newest day ≥ latest day due",
                )
                for m, s in (
                    ("exchange_inflow", inflow),
                    ("exchange_supply", supply),
                    ("revived_supply_1y", revived),
                )
                if has_dataset(m, asset)
            },
        }
        return result, change, context

    def _component(self, c: ComponentResult, context: dict[str, Any], asset: str) -> dict[str, Any]:
        d = c.definition
        cid = d.component_id
        if cid.startswith("exchange"):
            spec, evidence_class = dataset("exchange_inflow", asset), "attributed"
            fresh = context["freshness"]["exchange_inflow"]
        elif cid == "large_holders_7d":
            spec, evidence_class = dataset("address_balance", asset), "inferred"
            snaps = context["snapshots"]
            fresh = age_freshness(
                snaps[-1].time if snaps else None,
                SNAPSHOT_STALE_AFTER,
                context["knowledge_time"],
                "newest snapshot",
            )
        else:
            spec, evidence_class = dataset("revived_supply_1y", "BTC"), None
            fresh = context["freshness"].get(
                "revived_supply_1y", Freshness("no_data", None, None, None, "n/a", "not tracked")
            )
        notes = [c.reason] if c.reason else []
        if c.missing_days and c.status == "ok":
            notes.append(
                "missing inside the window (excluded): "
                + ", ".join(x.isoformat() for x in c.missing_days)
            )
        body = InstitutionalService.metric(
            metric_id=d.metric_id,
            label=d.label,
            evidence_category="metric",
            evidence_class=evidence_class,
            value=c.value,
            unit=d.unit,
            timestamp=c.latest_input or c.window_end,
            calculation=c.calculation or d.definition,
            source=self.source(spec),
            freshness=fresh,
            quality=quality_summary(
                status="ok"
                if c.status == "ok" and not c.missing_days
                else ("partial" if c.status == "ok" else "missing"),
                notes=notes,
                days_expected=c.days_expected or None,
                days_present=c.days_present if c.days_expected else None,
                flagged=c.flagged,
                revised=c.revised,
                backfilled=c.backfilled,
                estimated_availability=c.estimated_availability,
            ),
        )
        return {
            "component_id": cid,
            "status": c.status,
            "reason": c.reason,
            "definition": d.definition,
            "evidence": d.evidence,
            "weight": num(d.weight),
            "effective_weight": num(c.effective_weight),
            "reference_scale": num(d.scale),
            "sub_score": num(c.sub_score),
            "contribution": num(c.contribution),
            "window": {"start": c.window_start, "end": c.window_end},
            "inputs": c.inputs,
            "metric": body,
        }

    async def _institutional(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> tuple[Decimal | None, str]:
        if self.institutional is None:
            return None, "not_available"
        payload = await self.institutional.score(
            asset=asset, as_of=as_of, knowledge_time=knowledge_time
        )
        value = payload["value"]
        return (Decimal(value) if value is not None else None), payload["status"]

    @staticmethod
    def _exchange_change(
        context: dict[str, Any],
    ) -> tuple[Decimal | None, Decimal | None, dict[str, Any]]:
        """Labelled exchange addresses in the top 100 vs Coin Metrics exchange supply, same
        days (the two snapshot dates)."""
        snaps: list[ws.Snapshot] = context["snapshots"]
        now, then = ws.pick_snapshots(snaps, snaps[-1].time) if snaps else (None, None)
        if now is None or then is None:
            return None, None, {"note": "needs two top-100 snapshots 7 days apart"}
        rich = ws.holder_change(now, then, "exchange")
        supply: dict[date, ws.DayValue] = context["supply"]
        a, b = (
            supply.get(then.time.date() - timedelta(days=1)),
            supply.get(now.time.date() - timedelta(days=1)),
        )
        cm = (
            (b.value - a.value) / a.value * 100
            if a and b and a.value and b.value is not None
            else None
        )
        detail = {
            "labelled_exchange_addresses_compared": rich.matched,
            "labelled_balance_then": num(rich.balance_then),
            "labelled_balance_now": num(rich.balance_now),
            "coinmetrics_days": [
                (then.time.date() - timedelta(days=1)).isoformat(),
                (now.time.date() - timedelta(days=1)).isoformat(),
            ],
            "note": "Coin Metrics days are the complete UTC days before each snapshot",
        }
        return rich.change_pct if rich.matched else None, cm, detail

    async def score(
        self, *, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        asset = self._asset(asset)
        result, _, context = await self._score(asset, as_of, knowledge_time)
        inst_value, inst_status = await self._institutional(asset, as_of, knowledge_time)
        rich_pct, cm_pct, detail = self._exchange_change(context)
        checks = ws.contradictions(
            result,
            institutional_score=inst_value,
            institutional_status=inst_status,
            richlist_exchange_change_pct=rich_pct,
            coinmetrics_exchange_change_pct=cm_pct,
        )
        miner: ws.RatioResult | None = context["miner"]
        return {
            "score_id": ws.SCORE_ID,
            "version": ws.SCORE_VERSION,
            "asset": asset,
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "evidence_category": "metric",
            "status": result.status,
            "value": num(result.score),
            "unit": "points (−100 … +100)",
            "band": result.band,
            "reason": result.reason,
            "available_weight": num(result.available_weight),
            "calculation": (
                "score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components); "
                "positive = accumulation, negative = distribution"
            ),
            "window_end": context["window_end"],
            "components": [self._component(c, context, asset) for c in result.components],
            "contradictions": [
                {
                    "indicator_id": x.indicator_id,
                    "label": x.label,
                    "status": x.status,
                    "explanation": x.explanation,
                    "readings": [
                        {
                            "label": r.label,
                            "value": num(r.value),
                            "unit": r.unit,
                            "direction": r.direction,
                            "source": r.source,
                        }
                        for r in x.readings
                    ],
                    **(
                        {"detail": detail}
                        if x.indicator_id == "exchange_balances_two_sources"
                        else {}
                    ),
                }
                for x in checks
            ],
            "miner_spending": None
            if miner is None
            else {
                "metric_id": "miner_origin_spent_vs_issuance_7d.v1",
                "label": "Newly mined coins moved ÷ new issuance, last 7 days",
                "evidence_category": "metric",
                "status": miner.status,
                "value": num(miner.value),
                "unit": "ratio",
                "window": {"start": miner.window_start, "end": miner.window_end},
                "numerator_btc": num(miner.numerator),
                "denominator_btc": num(miner.denominator),
                "reason": miner.reason,
                "calculation": "Σ BTC spent from coinbase outputs ÷ Σ BTC issued, same 7 days",
                "note": "Not part of the score: coinbase outputs are mostly pool payouts, so the "
                "ratio shows how fast new coins move on, not whether miners sell.",
            },
            "interpretation_limits": INTERPRETATION_LIMITS,
            "bands_note": ws.BAND_NOTE,
        }

    async def overview(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        assets = []
        for asset in WHALE_ASSETS:
            result, _, context = await self._score(asset, as_of, knowledge_time)
            net = next(
                c for c in result.components if c.definition.component_id == "exchange_netflow_7d"
            )
            assets.append(
                {
                    "asset": asset,
                    "score": {
                        "status": result.status,
                        "value": num(result.score),
                        "band": result.band,
                        "reason": result.reason,
                        "available_weight": num(result.available_weight),
                    },
                    "netflow_7d": {
                        "status": net.status,
                        "value": net.inputs.get(f"net_flow_to_exchanges_{asset.lower()}"),
                        "pct_of_exchange_supply": num(net.value),
                        "unit": asset.lower(),
                        "window": {"start": net.window_start, "end": net.window_end},
                        "reason": net.reason,
                    },
                    "freshness": context["freshness"]["exchange_inflow"].as_dict(),
                }
            )
        return {
            "as_of": as_of,
            "knowledge_time": knowledge_time,
            "evidence_category": "metric",
            "assets": assets,
            "interpretation_limits": INTERPRETATION_LIMITS,
        }


def score_definition() -> dict[str, Any]:
    return {
        "score_id": ws.SCORE_ID,
        "version": ws.SCORE_VERSION,
        "evidence_category": "metric",
        "formula": "score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components)",
        "sub_score": "signed metric ÷ reference scale, capped to −1 … +1 (positive = accumulation)",
        "min_coverage": num(ws.MIN_COVERAGE),
        "min_available_weight": num(ws.MIN_AVAILABLE_WEIGHT),
        "min_holder_match": num(ws.MIN_HOLDER_MATCH),
        "components": [
            {
                "component_id": c.component_id,
                "metric_id": c.metric_id,
                "label": c.label,
                "weight": num(c.weight),
                "reference_scale": num(c.scale),
                "unit": c.unit,
                "definition": c.definition,
                "evidence": c.evidence,
            }
            for c in ws.COMPONENTS
        ],
        "bands": [{"lower_bound": num(lower), "label": label} for lower, label in ws.BANDS],
        "bands_note": ws.BAND_NOTE,
        "contradiction_rule": (
            f"A reading has a direction when its sub-score is at least ±{ws.DIRECTION_THRESHOLD}, "
            f"a score at least ±{ws.SCORE_DIRECTION} points, an exchange balance change at least "
            f"±{ws.SUPPLY_DIRECTION_PCT} %. Opposite directions = contradiction."
        ),
        "parameters_note": (
            "Weights, reference scales, thresholds and bands are judgment parameters chosen by "
            "design and published here; they are not fitted to price outcomes. Changing any of "
            "them creates a new score version."
        ),
        "interpretation_limits": INTERPRETATION_LIMITS,
    }
