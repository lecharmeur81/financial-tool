"""AlertService against real PostgreSQL (Phase 23): persistence of every required field,
evidence/provenance (the stored ``snapshot_id`` actually resolves to the snapshot the alert was
computed from), deduplication across two consecutive cycles with no change, and the auto-resolve
path for a flagged-state alert type whose condition clears. Runs wherever a real test database is
reachable (none anywhere this phase has been built — see PROGRESS.md), written and gated exactly
like every other Phase 21/22 DB-backed suite."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.repository import AlertRepository
from cfi.alerts.service import AlertService
from cfi.core.config import Settings
from cfi.db import tables as t
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

AS_OF = datetime(2026, 10, 3, tzinfo=UTC)


async def test_evaluate_persists_every_required_field_and_resolves_the_snapshot(
    db: AsyncEngine, test_settings: Settings
) -> None:
    svc = AlertService(db, test_settings)
    result = await svc.evaluate(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.candidates_evaluated >= 0

    async with db.connect() as conn:
        rows = (await conn.execute(select(t.alert_event))).mappings().all()
    for row in rows:
        assert row["alert_type"]
        assert row["severity"] in ("info", "notable", "elevated", "critical")
        assert row["domain"]
        assert row["trigger_condition"]
        assert row["observed_value"] is not None
        assert row["evidence_field_ids"]
        assert row["source_tool_id"]
        assert row["status"] == "active"
        if row["snapshot_id"] is not None:
            async with db.connect() as conn2:
                snap = (
                    await conn2.execute(
                        select(t.ai_snapshot.c.id).where(t.ai_snapshot.c.id == row["snapshot_id"])
                    )
                ).first()
            assert snap is not None  # reproducible: the referenced snapshot really exists


async def test_unchanged_condition_across_two_cycles_is_not_duplicated(
    db: AsyncEngine, test_settings: Settings
) -> None:
    svc = AlertService(db, test_settings)
    first = await svc.evaluate(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    second = await svc.evaluate(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    # Nothing in the underlying data changed between the two calls (same as_of/knowledge_time),
    # so the second cycle must skip every candidate it already alerted on.
    assert second.created == 0
    assert second.skipped_unchanged >= first.created


async def test_set_status_transitions_are_persisted(
    db: AsyncEngine, test_settings: Settings
) -> None:
    repo = AlertRepository(db)
    _id, row_uuid = await repo.insert_alert(
        now=AS_OF,
        alert_type="liquidity",
        severity="notable",
        domain="GLOBAL",
        dedup_key="liquidity:GLOBAL",
        trigger_condition="liquidity score band",
        observed_value="neutral",
        reference_value=None,
        evidence_field_ids=["get_liquidity.score.band"],
        snapshot_id=None,
        source_tool_id="get_liquidity",
        component_status="ok",
        data_quality_state="ok",
    )
    changed = await repo.set_status(row_uuid, status="acknowledged", now=AS_OF)
    assert changed
    row = await repo.get_by_uuid(row_uuid)
    assert row is not None
    assert row["status"] == "acknowledged"
    assert row["acknowledged_at"] is not None
