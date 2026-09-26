"""Record stores: persistence for each L1 record family (ADR-0017).

The ingestion engine is the same for every family; only these few operations differ:

- ``ObservationStore`` → ``obs.observation`` (one scalar ``value``);
- ``BarStore``         → ``obs.market_bar`` (OHLCV);
- ``FlowStore``        → ``obs.institutional_flow`` (flows and holdings of identified entities);
- ``TransferStore``    → ``obs.large_transfer`` (large on-chain transfers);
- ``QuoteStore``       → ``obs.derivative_quote`` (futures / option instruments in a snapshot).

All tables share the provenance columns and the natural key
(``series_id``, ``event_time``, ``source_provider``, ``revision``). Stores only ever *insert*
(append-only; a changed value becomes a new revision).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar, Protocol

from sqlalchemy import Row, Table, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.db import tables as t
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import (
    QUOTE_VALUE_FIELDS,
    CanonicalBar,
    CanonicalFlow,
    CanonicalObservation,
    CanonicalQuote,
    CanonicalTransfer,
    ObservedRecord,
)


class RecordStore[R: ObservedRecord](Protocol):
    async def latest_for_provider(
        self, series_id: int, event_times: Sequence[datetime], provider_id: str
    ) -> dict[datetime, tuple[int, object]]: ...

    async def latest_from_others(
        self, series_id: int, event_times: Sequence[datetime], provider_id: str
    ) -> dict[datetime, list[tuple[str, Decimal | None]]]: ...

    async def insert(self, rows: Sequence[tuple[int, R]]) -> int: ...

    async def latest_event_time(self, series_id: int, provider_id: str) -> datetime | None: ...

    def missing(self, template: R, event_time: datetime, gap: GapContext) -> R: ...


def _provenance(series_id: int, r: ObservedRecord) -> dict[str, Any]:
    return {
        "series_id": series_id,
        "event_time": r.event_time,
        "available_at": r.available_at,
        "available_at_estimated": r.available_at_estimated,
        "ingested_at": r.ingested_at,
        "source_provider": r.source_provider,
        "original_source": r.original_source,
        "raw_ref": r.raw_ref,
        "revision": r.revision,
        "pit_reliability": str(r.pit_reliability),
        "quality_status": str(r.quality_status),
        "quality_note": r.quality_note,
        "confidence": r.confidence,
        "transformations": list(r.transformations),
    }


@dataclass(frozen=True, slots=True)
class GapContext:
    """Who is reporting a gap, when, and how to describe it."""

    provider_id: str
    original_source: str
    now: datetime
    note: str


def _missing_provenance(
    template: ObservedRecord, event_time: datetime, gap: GapContext
) -> dict[str, Any]:
    """Provenance for an explicit gap row: same series as ``template``, no value."""
    return {
        "dataset_id": template.dataset_id,
        "metric": template.metric,
        "asset": template.asset,
        "subject_ref": template.subject_ref,
        "venue": template.venue,
        "period": template.period,
        "unit": template.unit,
        "event_time": event_time,
        "available_at": gap.now,
        "available_at_estimated": True,
        "ingested_at": gap.now,
        "source_provider": gap.provider_id,
        "original_source": gap.original_source,
        "quality_status": QualityStatus.MISSING,
        "quality_note": gap.note,
        "pit_reliability": PitReliability.NATIVE,
    }


class _TableStore:
    """Queries shared by both families; subclasses name their table and value columns."""

    table: ClassVar[Table]
    value_columns: ClassVar[tuple[str, ...]]
    conflict_column: ClassVar[str]

    def __init__(self, engine: AsyncEngine) -> None:
        self.engine = engine

    def _comparable(self, row: Row[Any]) -> object:
        values = tuple(getattr(row, c) for c in self.value_columns)
        return values[0] if len(values) == 1 else values

    async def latest_for_provider(
        self, series_id: int, event_times: Sequence[datetime], provider_id: str
    ) -> dict[datetime, tuple[int, object]]:
        """Latest stored revision (and its values) per event time, for one provider."""
        if not event_times:
            return {}
        tb = self.table
        stmt = (
            select(tb.c.event_time, tb.c.revision, *(tb.c[c] for c in self.value_columns))
            .distinct(tb.c.event_time)
            .where(
                tb.c.series_id == series_id,
                tb.c.source_provider == provider_id,
                tb.c.event_time.in_(list(event_times)),
            )
            .order_by(tb.c.event_time, tb.c.revision.desc())
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        return {r.event_time: (int(r.revision), self._comparable(r)) for r in rows}

    async def latest_from_others(
        self, series_id: int, event_times: Sequence[datetime], provider_id: str
    ) -> dict[datetime, list[tuple[str, Decimal | None]]]:
        """Latest revision per (event time, other provider) — the value compared for conflicts."""
        if not event_times:
            return {}
        tb = self.table
        stmt = (
            select(tb.c.event_time, tb.c.source_provider, tb.c[self.conflict_column].label("v"))
            .distinct(tb.c.event_time, tb.c.source_provider)
            .where(
                tb.c.series_id == series_id,
                tb.c.source_provider != provider_id,
                tb.c.event_time.in_(list(event_times)),
            )
            .order_by(tb.c.event_time, tb.c.source_provider, tb.c.revision.desc())
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        out: dict[datetime, list[tuple[str, Decimal | None]]] = {}
        for r in rows:
            out.setdefault(r.event_time, []).append((r.source_provider, r.v))
        return out

    async def latest_event_time(self, series_id: int, provider_id: str) -> datetime | None:
        """Newest event time holding a real (non-missing) value."""
        tb = self.table
        stmt = select(func.max(tb.c.event_time)).where(
            tb.c.series_id == series_id,
            tb.c.source_provider == provider_id,
            tb.c.quality_status != "missing",
        )
        async with self.engine.connect() as conn:
            value: datetime | None = (await conn.execute(stmt)).scalar()
        return value

    async def _insert(self, values: list[dict[str, Any]]) -> int:
        if not values:
            return 0
        async with self.engine.begin() as conn:
            await conn.execute(insert(self.table), values)
        return len(values)


class ObservationStore(_TableStore):
    table = t.observation
    value_columns = ("value",)
    conflict_column = "value"

    async def insert(self, rows: Sequence[tuple[int, CanonicalObservation]]) -> int:
        return await self._insert([{**_provenance(sid, o), "value": o.value} for sid, o in rows])

    def missing(
        self, template: CanonicalObservation, event_time: datetime, gap: GapContext
    ) -> CanonicalObservation:
        return CanonicalObservation(**_missing_provenance(template, event_time, gap), value=None)


class BarStore(_TableStore):
    table = t.market_bar
    value_columns = (
        "open",
        "high",
        "low",
        "close",
        "volume_base",
        "volume_quote",
        "trade_count",
    )
    conflict_column = "close"

    async def insert(self, rows: Sequence[tuple[int, CanonicalBar]]) -> int:
        return await self._insert(
            [
                {
                    **_provenance(sid, b),
                    "open": b.open,
                    "high": b.high,
                    "low": b.low,
                    "close": b.close,
                    "volume_base": b.volume_base,
                    "volume_quote": b.volume_quote,
                    "trade_count": b.trade_count,
                }
                for sid, b in rows
            ]
        )

    def missing(
        self, template: CanonicalBar, event_time: datetime, gap: GapContext
    ) -> CanonicalBar:
        return CanonicalBar(
            **_missing_provenance(template, event_time, gap),
            open=None,
            high=None,
            low=None,
            close=None,
            volume_base=None,
        )


FLOW_VALUE_COLUMNS = (
    "flow_usd",
    "flow_native",
    "holdings_usd",
    "holdings_native",
    "cum_flow_usd",
    "value_traded_usd",
    "premium_discount",
    "unit_cost_usd",
)


class FlowStore(_TableStore):
    table = t.institutional_flow
    value_columns = FLOW_VALUE_COLUMNS
    conflict_column = "flow_usd"

    async def latest_from_others(
        self, series_id: int, event_times: Sequence[datetime], provider_id: str
    ) -> dict[datetime, list[tuple[str, Decimal | None]]]:
        """Compared value: the flow in USD, or coin holdings when no flow is reported (same
        rule as :attr:`CanonicalFlow.conflict_value`)."""
        if not event_times:
            return {}
        tb = self.table
        value = func.coalesce(tb.c.flow_usd, tb.c.holdings_native).label("v")
        stmt = (
            select(tb.c.event_time, tb.c.source_provider, value)
            .distinct(tb.c.event_time, tb.c.source_provider)
            .where(
                tb.c.series_id == series_id,
                tb.c.source_provider != provider_id,
                tb.c.event_time.in_(list(event_times)),
            )
            .order_by(tb.c.event_time, tb.c.source_provider, tb.c.revision.desc())
        )
        async with self.engine.connect() as conn:
            rows = (await conn.execute(stmt)).all()
        out: dict[datetime, list[tuple[str, Decimal | None]]] = {}
        for r in rows:
            out.setdefault(r.event_time, []).append((r.source_provider, r.v))
        return out

    async def insert(self, rows: Sequence[tuple[int, CanonicalFlow]]) -> int:
        return await self._insert(
            [
                {
                    **_provenance(sid, f),
                    "entity_type": f.entity_type,
                    "evidence_class": str(f.evidence_class),
                    "entity_name": f.entity_name,
                    **{c: getattr(f, c) for c in FLOW_VALUE_COLUMNS},
                }
                for sid, f in rows
            ]
        )

    def missing(
        self, template: CanonicalFlow, event_time: datetime, gap: GapContext
    ) -> CanonicalFlow:
        return CanonicalFlow(
            **_missing_provenance(template, event_time, gap),
            entity_type=template.entity_type,
            evidence_class=template.evidence_class,
            entity_name=template.entity_name,
        )


TRANSFER_VALUE_COLUMNS = (
    "tx_hash",
    "output_index",
    "block_height",
    "sender",
    "recipient",
    "value_native",
    "value_usd",
)


class TransferStore(_TableStore):
    table = t.large_transfer
    value_columns = TRANSFER_VALUE_COLUMNS
    conflict_column = "value_native"

    async def insert(self, rows: Sequence[tuple[int, CanonicalTransfer]]) -> int:
        return await self._insert(
            [
                {
                    **_provenance(sid, x),
                    "chain": x.chain,
                    **{c: getattr(x, c) for c in TRANSFER_VALUE_COLUMNS},
                }
                for sid, x in rows
            ]
        )

    def missing(
        self, template: CanonicalTransfer, event_time: datetime, gap: GapContext
    ) -> CanonicalTransfer:
        return CanonicalTransfer(
            **_missing_provenance(template, event_time, gap),
            chain=template.chain,
            tx_hash=template.tx_hash,
            output_index=template.output_index,
        )


class QuoteStore(_TableStore):
    table = t.derivative_quote
    value_columns = QUOTE_VALUE_FIELDS
    conflict_column = "mark_price"

    async def insert(self, rows: Sequence[tuple[int, CanonicalQuote]]) -> int:
        return await self._insert(
            [
                {
                    **_provenance(sid, q),
                    "instrument": q.instrument,
                    "instrument_kind": q.instrument_kind,
                    "expiry": q.expiry,
                    "strike": q.strike,
                    "option_type": q.option_type,
                    **{c: getattr(q, c) for c in QUOTE_VALUE_FIELDS},
                }
                for sid, q in rows
            ]
        )

    def missing(
        self, template: CanonicalQuote, event_time: datetime, gap: GapContext
    ) -> CanonicalQuote:
        return CanonicalQuote(
            **_missing_provenance(template, event_time, gap),
            instrument=template.instrument,
            instrument_kind=template.instrument_kind,
            expiry=template.expiry,
            strike=template.strike,
            option_type=template.option_type,
        )
