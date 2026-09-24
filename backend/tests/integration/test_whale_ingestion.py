"""Whale ingestion and labels against real PostgreSQL + TimescaleDB: the real adapters, engine,
jobs and label store, fed by fake provider servers (tests/fixtures/whales/README.md)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from cfi.domain.enums import EvidenceClass
from cfi.providers import blockchair, coinmetrics
from cfi.whales.label_store import (
    SEED_FILES,
    import_labels,
    import_seed_files,
    load_entities,
    load_labels,
)
from cfi.whales.labels import Entity, Label, LabelError, LabelFile
from cfi.whales.sources import source
from cfi.whales.universe import dataset
from tests.integration.conftest import requires_services
from tests.integration.whale_support import BINANCE, NOW, UNKNOWN, WhaleHarness, snapshot_now
from tests.whale_fakes import LAST_DAY, btc_address

pytestmark = [pytest.mark.integration, requires_services]


# ------------------------------------------------------------------ labels in the database


async def test_seed_labels_import_once_and_never_duplicate(whales: WhaleHarness) -> None:
    [first] = await import_seed_files(whales.db, NOW)
    assert (first.labels_added, first.labels_existing) == (27, 0)
    assert first.entities_added == 14
    [again] = await import_seed_files(whales.db, NOW + timedelta(hours=1))
    assert (again.labels_added, again.labels_existing, again.entities_added) == (0, 27, 0)
    labels = await load_labels(whales.db, chain="bitcoin")
    assert len(labels) == 27
    assert {lb.recorded_at for lb in labels} == {NOW}  # the first import is kept as it was
    binance = [lb for lb in labels if lb.address == BINANCE]
    assert [(lb.actor_class, lb.entity_id) for lb in binance] == [("exchange", "binance")]
    entities = await load_entities(whales.db)
    assert entities["tether"].actor_class == "institution"
    assert SEED_FILES


async def test_stored_entity_is_never_overwritten(whales: WhaleHarness) -> None:
    await import_seed_files(whales.db, NOW)
    changed = LabelFile(
        {"binance": Entity("binance", "Binance", "fund")},
        (),
    )
    with pytest.raises(LabelError, match="not overwritten"):
        await import_labels(whales.db, changed, NOW)


def _insert_sql(actor: str, entity: str | None, evidence: str) -> str:
    entity_sql = "NULL" if entity is None else f"'{entity}'"
    columns = (
        "chain, address, actor_class, entity_id, evidence_class, confidence, evidence, source, "
        "available_at, recorded_at"
    )
    values = (
        f"'bitcoin', '{btc_address(5)}', '{actor}', {entity_sql}, '{evidence}', 0.5, 'size', "
        "'rule', now(), now()"
    )
    return f"INSERT INTO ref.entity_label ({columns}) VALUES ({values})"  # noqa: S608 — test only


@pytest.mark.parametrize(
    ("actor", "entity", "evidence", "constraint"),
    [
        ("institution", "tether", "inferred", "label_inferred_only_unknown"),
        ("fund", "tether", "inferred", "label_inferred_only_unknown"),
        ("market_maker", "tether", "inferred", "label_inferred_only_unknown"),
        ("exchange", "binance", "inferred", "label_inferred_only_unknown"),
        ("unknown_large_holder", "binance", "inferred", "label_known_needs_entity"),
        ("exchange", None, "attributed", "label_known_needs_entity"),
        ("whale", None, "inferred", "entity_label_actor_class_check"),
    ],
)
async def test_database_rejects_labels_that_break_the_rules(
    whales: WhaleHarness, actor: str, entity: str | None, evidence: str, constraint: str
) -> None:
    """R5 enforced by the database itself: no code path can store an inferred institution."""
    await import_seed_files(whales.db, NOW)
    with pytest.raises(IntegrityError, match=constraint):
        async with whales.db.begin() as conn:
            await conn.execute(text(_insert_sql(actor, entity, evidence)))


async def test_database_accepts_an_inferred_unknown_large_holder(whales: WhaleHarness) -> None:
    async with whales.db.begin() as conn:
        await conn.execute(text(_insert_sql("unknown_large_holder", None, "inferred")))
    [lb] = await load_labels(whales.db)
    assert (lb.actor_class, lb.evidence_class) == ("unknown_large_holder", EvidenceClass.INFERRED)


async def test_import_of_new_label_for_known_entity(whales: WhaleHarness) -> None:
    await import_seed_files(whales.db, NOW)
    new = Label(
        chain="bitcoin",
        address=btc_address(9),
        actor_class="exchange",
        entity_id="binance",
        evidence_class=EvidenceClass.DIRECT,
        confidence=Decimal("0.95"),
        evidence="published in the exchange's proof-of-reserves list",
        source="Binance",
        available_at=datetime(2026, 9, 24, tzinfo=UTC),
    )
    result = await import_labels(
        whales.db, LabelFile({"binance": Entity("binance", "Binance", "exchange")}, (new,)), NOW
    )
    assert (result.labels_added, result.entities_existing) == (1, 1)


# ------------------------------------------------------------------ ingestion


async def test_coinmetrics_daily_history_is_loaded_in_chunks(whales: WhaleHarness) -> None:
    item = source(coinmetrics.PROVIDER_ID, dataset("exchange_inflow", "BTC").dataset_id, "BTC")
    first = await whales.run_source(item)
    assert [r.job_type for r in first] == ["ingest", "backfill"]
    assert all(r.status == "succeeded" for r in first)
    assert first[0].pages == 1  # 35 days < the fake's 100-row pages
    assert first[1].pages == 2  # 146 days of history in 100-row pages
    rows = await whales.rows(
        "SELECT o.event_time, o.value, o.quality_status, o.available_at, o.revision"
        "  FROM obs.observation o JOIN obs.series s USING (series_id)"
        " WHERE s.dataset_id = 'whale.exchange_inflow.btc.1d' ORDER BY o.event_time, o.revision"
    )
    distinct = {r["event_time"] for r in rows}
    assert len(distinct) == 146  # 2026-04-17 … 2026-09-09, duplicates not stored twice
    assert len(rows) == 146
    last = rows[-1]
    assert last["quality_status"] == "estimated"  # 'flash'
    assert last["available_at"] == datetime(2026, 9, 10, 2, tzinfo=UTC)
    assert rows[0]["quality_status"] == "ok"  # 'reviewed'
    again = await whales.run_source(item, times=2)
    assert again[0].duplicates == 35  # the 35 complete days of the window are all stored
    assert [r.job_type for r in again] == ["ingest", "backfill", "ingest"]  # history completed
    state = await whales.rows("SELECT complete, note FROM ops.backfill_state")
    assert state == [{"complete": True, "note": "history loaded back to 2024-09-10"}]


async def test_provider_revision_is_appended_not_overwritten(whales: WhaleHarness) -> None:
    item = source(coinmetrics.PROVIDER_ID, dataset("exchange_inflow", "BTC").dataset_id, "BTC")
    await whales.run_source(item)
    whales.cm.overrides[("btc", "FlowInExNtv", LAST_DAY)] = Decimal(27_000)
    whales.wall.advance(timedelta(hours=1))
    [result, _] = await whales.run_source(item)
    assert result.revisions == 1
    rows = await whales.rows(
        "SELECT o.value, o.revision FROM obs.observation o JOIN obs.series s USING (series_id)"
        " WHERE s.dataset_id = 'whale.exchange_inflow.btc.1d'"
        "   AND o.event_time = '2026-09-09T00:00:00Z' ORDER BY o.revision"
    )
    assert rows == [
        {"value": Decimal(20_000), "revision": 0},
        {"value": Decimal(27_000), "revision": 1},
    ]


async def test_rich_list_snapshot_is_stored_per_address(whales: WhaleHarness) -> None:
    whales.bc.btc_snapshot = snapshot_now()
    [result] = await whales.run(blockchair.PROVIDER_ID, "address_balance", "BTC")
    assert (result.status, result.inserted, result.rejected) == ("succeeded", 13, 0)
    rows = await whales.rows(
        "SELECT s.subject_ref, o.value, o.event_time, o.available_at_estimated"
        "  FROM obs.observation o JOIN obs.series s USING (series_id)"
        " WHERE s.dataset_id = 'whale.address_balance.bitcoin' ORDER BY o.value DESC"
    )
    assert rows[0]["subject_ref"] == f"bitcoin:{BINANCE}"
    assert rows[0]["value"] == Decimal(245_000)
    assert {r["event_time"] for r in rows} == {NOW}  # one snapshot = one receipt time
    assert all(r["available_at_estimated"] for r in rows)


async def test_transfers_are_stored_with_invalid_addresses_flagged(whales: WhaleHarness) -> None:
    from tests.integration.whale_support import transfers

    transfers(whales.bc)
    item = source(blockchair.PROVIDER_ID, dataset("large_transfer", "BTC").dataset_id, "BTC")
    results = await whales.run_source(item, times=8)
    assert sum(r.inserted for r in results) == 3
    # the flagged output is re-checked (and counted) on every re-read, stored once
    assert sum(r.suspect for r in results) >= 1
    rows = await whales.rows(
        "SELECT recipient, value_native, quality_status, quality_note, output_index"
        "  FROM obs.large_transfer ORDER BY event_time"
    )
    assert [r["value_native"] for r in rows] == [Decimal(1_200), Decimal(800), Decimal(600)]
    assert rows[0]["recipient"] == BINANCE
    assert rows[1]["recipient"] == UNKNOWN[0]
    assert rows[2]["quality_status"] == "suspect"
    assert "not a valid bitcoin address" in rows[2]["quality_note"]
    # re-reading the same windows stores nothing twice
    again = await whales.run_source(item)
    assert sum(r.inserted for r in again) == 0


async def test_blockchair_aggregates_load_history_and_skip_today(whales: WhaleHarness) -> None:
    item = source(blockchair.PROVIDER_ID, dataset("revived_supply_1y", "BTC").dataset_id, "BTC")
    results = await whales.run_source(item, times=6)
    assert all(r.status == "succeeded" for r in results)
    rows = await whales.rows(
        "SELECT min(o.event_time) AS first, max(o.event_time) AS last, count(*) AS n"
        "  FROM obs.observation o JOIN obs.series s USING (series_id)"
        " WHERE s.dataset_id = 'whale.revived_supply_1y.btc.1d'"
    )
    assert rows == [
        {
            "first": datetime(2026, 5, 13, tzinfo=UTC),
            "last": datetime(2026, 9, 9, tzinfo=UTC),
            "n": 120,
        }
    ]


async def test_provider_error_fails_the_run_and_keeps_the_history_position(
    whales: WhaleHarness,
) -> None:
    import httpx2

    item = source(blockchair.PROVIDER_ID, dataset("coin_days_destroyed", "BTC").dataset_id, "BTC")

    async def refuse(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(402, content=b'{"data":null,"context":{"code":402}}')

    whales.ctx.clients[blockchair.PROVIDER_ID]._client._transport = httpx2.MockTransport(refuse)
    results = await whales.run_source(item)
    assert [r.status for r in results] == ["failed", "failed"]
    assert results[0].error_code is not None
    assert await whales.rows("SELECT * FROM ops.backfill_state") == []  # retried next run
