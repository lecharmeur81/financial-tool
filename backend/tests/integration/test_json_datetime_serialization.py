"""Regression coverage for Phase 30 finding F-1 / Phase 31 fix: every ``JSONB`` column that can
receive live application data (most importantly ``cfi.analyst.snapshot.Snapshot.payload()``,
whose ``tool_results`` key carries the 14 domain tools' raw output verbatim, including real
``datetime`` values once the database is non-empty) must round-trip through the database without
raising ``TypeError: Object of type datetime is not JSON serializable``.

Every previously-failing integration test (``test_alerts_service.py``, ``test_analyst_service.py``,
``test_brief_service.py``, and the snapshot-insert step inside ``test_paper_service.py``/
``test_journal_service.py``) reached this exact failure through ``AnalystRepository.
insert_snapshot``/``mark_completed`` or ``BriefRepository.mark_completed``, so this file tests the
shared chokepoint directly, with a realistic (not synthetic/trivial) datetime-bearing payload, and
then proves the fix is end-to-end effective by running ``build_snapshot`` against a genuinely
non-empty database (the exact scenario the project's "insufficient data"/empty-database testing
convention had never exercised).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.service import AlertService
from cfi.analyst.repository import AnalystRepository
from cfi.analyst.snapshot import build_snapshot
from cfi.brief.repository import BriefRepository
from cfi.core.config import Settings
from cfi.market.jobs import backfill_step
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ohlcv_dataset
from tests.integration.conftest import requires_services
from tests.integration.market_support import NOW, MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

DAILY = ohlcv_dataset("usd", "1d")
AS_OF = NOW


async def _seed_btc(market: MarketHarness) -> None:
    await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, "BTC", depth_days=60)


def _payload_with_live_objects() -> dict[str, object]:
    """Shaped like a real ``Snapshot.payload()``: top-level fields are already strings (as
    ``Snapshot.payload()`` itself produces), but ``tool_results`` carries raw, unconverted
    ``datetime``/``date``/``Decimal`` values exactly as a domain tool's own return value would —
    the precise shape that previously raised ``TypeError`` on insert."""
    return {
        "snapshot_version": "analyst_snapshot.v1",
        "as_of": AS_OF.isoformat(),
        "knowledge_time": AS_OF.isoformat(),
        "question": None,
        "tools_called": ["get_market_data"],
        "not_tracked": [],
        "data_quality_state": "ok",
        "has_conflicts": False,
        "fields": {},
        "tool_results": {
            "get_market_data": {
                "status": "ok",
                "data": {
                    "last_bar_time": datetime(2026, 9, 1, tzinfo=UTC),
                    "last_bar_date": date(2026, 9, 1),
                    "close": Decimal("67432.187"),
                },
                "error": None,
            }
        },
    }


async def test_insert_snapshot_succeeds_with_a_live_datetime_bearing_payload(
    db: AsyncEngine,
) -> None:
    """The exact Phase 30 F-1 reproduction at the shared chokepoint every Analyst/Brief/Alerts/
    Paper/Journal write passes through."""
    repo = AnalystRepository(db)
    now = datetime.now(UTC)
    snapshot_id, _uuid = await repo.insert_snapshot(
        created_at=now,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        snapshot_version="analyst_snapshot.v1",
        payload=_payload_with_live_objects(),
        payload_hash="f1-regression-hash",
    )
    assert snapshot_id is not None


async def test_analyst_mark_completed_response_field_tolerates_a_datetime_value(
    db: AsyncEngine,
) -> None:
    """``ai.interpretation.response`` is a second, independent ``JSONB`` write path named in the
    Phase 30 report; it must survive a response dict containing a live ``datetime`` just as
    readily as ``insert_snapshot`` does."""
    repo = AnalystRepository(db)
    now = datetime.now(UTC)
    snapshot_id, _uuid = await repo.insert_snapshot(
        created_at=now,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        snapshot_version="analyst_snapshot.v1",
        payload={"fields": {}},
        payload_hash="f1-regression-hash-2",
    )
    interpretation_id, _analysis_uuid = await repo.create_queued_interpretation(
        now=now, question=None
    )
    await repo.mark_completed(
        interpretation_id,
        now=now,
        snapshot_id=snapshot_id,
        prompt_version="analyst_prompt.v1",
        model="claude-sonnet-5",
        response={"summary": "Insufficient data.", "as_of_echo": AS_OF},  # live datetime on purpose
        validation_status="ok",
        validation_errors=[],
        attempt_count=1,
        tools_called=["get_market_data"],
        data_quality_state="ok",
    )
    row = await repo.get_by_uuid(_analysis_uuid)
    assert row is not None
    assert row["status"] == "completed"


async def test_brief_mark_completed_changes_field_tolerates_a_datetime_value(
    db: AsyncEngine,
) -> None:
    """``ai.brief.changes`` is the Brief-specific ``JSONB`` column named in the Phase 30 report."""
    analyst_repo = AnalystRepository(db)
    brief_repo = BriefRepository(db)
    now = datetime.now(UTC)
    snapshot_id, _uuid = await analyst_repo.insert_snapshot(
        created_at=now,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        snapshot_version="analyst_snapshot.v1",
        payload={"fields": {}},
        payload_hash="f1-regression-hash-3",
    )
    brief_db_id, brief_uuid = await brief_repo.create_queued_brief(
        now=now, reporting_period_start=AS_OF, reporting_period_end=now, previous_brief_id=None
    )
    await brief_repo.mark_completed(
        brief_db_id,
        now=now,
        snapshot_id=snapshot_id,
        prompt_version="brief_prompt.v1",
        analyst_version="brief_analyst.v1",
        model="claude-sonnet-5",
        response={"executive_summary": "Insufficient data."},
        validation_status="ok",
        validation_errors=[],
        attempt_count=1,
        tools_called=["get_market_data"],
        data_quality_state="ok",
        changes={"comparison_basis": "none", "changes": [], "computed_at": AS_OF},  # live datetime
    )
    row = await brief_repo.get_by_uuid(brief_uuid)
    assert row is not None
    assert row["status"] == "completed"


async def test_build_snapshot_against_a_non_empty_database_inserts_cleanly(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    """The faithful end-to-end reproduction: seed real (fake-provider-backed) OHLCV bars — which
    carry genuine ``datetime`` values in their raw tool output — then build and insert a real
    snapshot exactly as ``AnalystService``/``BriefService``/``AlertService`` do. This is the exact
    scenario that was previously impossible to even construct, because every pre-existing
    Analyst/Brief/Alerts integration test ran against an empty database."""
    await _seed_btc(market)
    snapshot = await build_snapshot(
        db, test_settings, as_of=AS_OF, knowledge_time=AS_OF, question=None
    )
    repo = AnalystRepository(db)
    snapshot_id, _uuid = await repo.insert_snapshot(
        created_at=snapshot.created_at,
        as_of=snapshot.as_of,
        knowledge_time=snapshot.knowledge_time,
        snapshot_version=snapshot.snapshot_version,
        payload=snapshot.payload(),
        payload_hash=snapshot.snapshot_id,
    )
    assert snapshot_id is not None


async def test_alert_service_evaluate_against_a_non_empty_database_completes(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    """``AlertService.evaluate()`` calls ``build_snapshot`` + ``insert_snapshot`` internally
    (Phase 30 F-1's exact first reproduction, via ``test_alerts_service.py``) — confirm the full
    service call now completes against real, non-empty data instead of raising ``TypeError``."""
    await _seed_btc(market)
    svc = AlertService(db, test_settings)
    result = await svc.evaluate(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result is not None
