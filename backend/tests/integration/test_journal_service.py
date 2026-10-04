"""DecisionJournalService against real PostgreSQL (Phase 25): decision creation, decision-time
snapshot capture, thesis preservation, outcome recording, hindsight protection, invalidation
conditions, paper-trade linking, alert/brief linking, historical review, missing data, and
invalid state transitions. Runs wherever a real test database is reachable (none anywhere this
phase has been built — see PROGRESS.md), written and gated exactly like every other Phase 21-24
DB-backed suite ("DB integration tests may remain unexecuted if the same PostgreSQL environment
limitation continues").

Seeds real Coinbase-shaped daily bars through the same fake-provider harness Phase 24's own paper
suite already uses (``tests.integration.market_support.MarketHarness``)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.repository import AlertRepository
from cfi.core.config import Settings
from cfi.core.errors import DataValidationError, NotFoundError
from cfi.journal.repository import DecisionJournalRepository
from cfi.journal.service import DecisionJournalOutcomeInput, DecisionJournalService
from cfi.market.jobs import backfill_step
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ohlcv_dataset
from cfi.paper.service import PaperTradingService
from tests.integration.conftest import requires_services
from tests.integration.market_support import NOW, MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

DAILY = ohlcv_dataset("usd", "1d")
DECISION_AS_OF = NOW - timedelta(days=30)
OUTCOME_AS_OF = NOW


async def _seed_btc(market: MarketHarness) -> None:
    """Seed 280 days of BTC daily bars, then realign each bar's ``ingested_at`` to its own
    ``available_at`` (the exact convention Phase 16's backtest fixtures already use for synthetic
    bars — see ``test_backtest_engine.py``) rather than leaving it at the single moment this one
    bulk ``backfill_step`` call ran.

    This matters only because this suite deliberately exercises a *point-in-time* lookup
    (``DECISION_AS_OF`` is 30 days before ``OUTCOME_AS_OF``), unlike every other ``MarketHarness``
    consumer, which only ever queries "as of now" (``NOW``, the same moment the harness's wall
    clock is fixed to). ``cfi.market.queries.MarketQueries.bars`` correctly requires
    ``ingested_at <= as_of`` (knowledge-time, not just real-world availability) — a single bulk
    backfill stamps every row with the one moment *that job* ran, which is accurate for a real
    deployment (a backfill always precedes the "now" that queries it) but is not a faithful
    stand-in for "this bar was ingested shortly after its own day closed," which is what a
    decision 30 days in the past needs in order to see it. Setting ``ingested_at = available_at``
    keeps every bar's point-in-time/knowledge-time gating fully enforced (R3) — it only makes the
    simulated ingestion timeline realistic instead of an artifact of when this test happened to
    call ``backfill_step``."""
    await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, "BTC", depth_days=280)
    async with market.db.begin() as conn:
        await conn.execute(text("UPDATE obs.market_bar SET ingested_at = available_at"))


async def test_create_decision_persists_thesis_fields_and_a_decision_snapshot(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = DecisionJournalService(db, test_settings)
    row = await svc.create_decision(
        asset="BTC",
        decision_type="long_spot",
        thesis="ETF inflows diverging from retail funding suggests institutional accumulation.",
        expected_scenario="BTC grinds higher over the next 2-4 weeks as ETF inflows continue.",
        invalidation_condition="BTC closes below 55000 on a daily basis.",
        confidence=Decimal("0.6"),
        now=DECISION_AS_OF,
    )
    assert row["status"] == "open"
    assert row["asset"] == "BTC"
    assert row["decision_type"] == "long_spot"
    assert row["thesis"].startswith("ETF inflows diverging")
    assert row["decision_snapshot_id"] is not None  # "Decision-time context" is required
    assert row["observed_price_at_decision"] is not None  # BTC is tracked, data is seeded
    assert row["relevant_alert_ids"] == []  # none active — contextual evidence, not fabricated
    assert row["market_brief_id"] is None  # no completed brief exists yet


async def test_create_decision_never_invents_a_confidence_value(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """ "Do not invent user decisions or confidence levels" — a decision with no stated
    confidence stores ``None``, never a default or fabricated figure."""
    svc = DecisionJournalService(db, test_settings)
    row = await svc.create_decision(
        asset="ETH", decision_type="watch", thesis="Monitoring funding before taking a position."
    )
    assert row["confidence"] is None


async def test_untracked_asset_still_creates_a_decision_without_an_observed_price(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """A journal entry is not restricted to the platform's 4 tracked assets — only the optional
    auto-captured price is ("Entry/observation price if provided" — never invented)."""
    svc = DecisionJournalService(db, test_settings)
    row = await svc.create_decision(
        asset="SOME_ALTCOIN", decision_type="watch", thesis="Watching for now."
    )
    assert row["asset"] == "SOME_ALTCOIN"
    assert row["observed_price_at_decision"] is None


async def test_empty_thesis_is_rejected_before_any_snapshot_is_built(
    db: AsyncEngine, test_settings: Settings
) -> None:
    svc = DecisionJournalService(db, test_settings)
    with pytest.raises(DataValidationError):
        await svc.create_decision(asset="BTC", decision_type="long_spot", thesis="   ")


async def test_out_of_range_confidence_is_rejected(
    db: AsyncEngine, test_settings: Settings
) -> None:
    svc = DecisionJournalService(db, test_settings)
    with pytest.raises(DataValidationError):
        await svc.create_decision(
            asset="BTC",
            decision_type="long_spot",
            thesis="Thesis.",
            confidence=Decimal("1.5"),
        )


async def test_record_outcome_never_rewrites_the_original_thesis(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    """Hindsight protection ("Do not rewrite the original thesis after the outcome becomes
    known... Never silently modify the original decision record based on the outcome")."""
    await _seed_btc(market)
    svc = DecisionJournalService(db, test_settings)
    created = await svc.create_decision(
        asset="BTC",
        decision_type="long_spot",
        thesis="Original thesis text.",
        expected_scenario="Original expected scenario.",
        invalidation_condition="Original invalidation condition.",
        now=DECISION_AS_OF,
    )
    outcome_input = DecisionJournalOutcomeInput(
        outcome="not_as_expected",
        thesis_supported=False,
        thesis_contradicted=True,
        invalidation_occurred=True,
        evidence_changed_notes="Funding flipped negative shortly after.",
        actual_market_movement_text="BTC dropped 8% over the following week.",
        lessons_notes="Underweighted the funding signal.",
        status="invalidated",
    )
    resolved = await svc.record_outcome(
        created["uuid"], outcome_input=outcome_input, now=OUTCOME_AS_OF
    )
    assert resolved["thesis"] == "Original thesis text."
    assert resolved["expected_scenario"] == "Original expected scenario."
    assert resolved["invalidation_condition"] == "Original invalidation condition."
    assert resolved["decision_time"] == created["decision_time"]
    assert resolved["decision_snapshot_id"] == created["decision_snapshot_id"]
    assert resolved["observed_price_at_decision"] == created["observed_price_at_decision"]
    # Only the outcome columns changed.
    assert resolved["status"] == "invalidated"
    assert resolved["outcome"] == "not_as_expected"
    assert resolved["thesis_contradicted"] is True
    assert resolved["actual_price_at_outcome"] is not None
    assert resolved["actual_market_movement_pct"] is not None
    assert resolved["outcome_timestamp"] is not None


async def test_cancel_an_open_decision_records_no_outcome(
    db: AsyncEngine, test_settings: Settings
) -> None:
    svc = DecisionJournalService(db, test_settings)
    created = await svc.create_decision(asset="ETH", decision_type="watch", thesis="Just watching.")
    cancelled = await svc.cancel_decision(created["uuid"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["outcome"] is None
    assert cancelled["outcome_timestamp"] is None


async def test_resolving_an_already_resolved_decision_is_rejected(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = DecisionJournalService(db, test_settings)
    created = await svc.create_decision(
        asset="BTC", decision_type="long_spot", thesis="Thesis.", now=DECISION_AS_OF
    )
    outcome_input = DecisionJournalOutcomeInput(
        outcome="as_expected",
        thesis_supported=True,
        thesis_contradicted=False,
        invalidation_occurred=False,
        evidence_changed_notes=None,
        actual_market_movement_text=None,
        lessons_notes=None,
        status="resolved",
    )
    await svc.record_outcome(created["uuid"], outcome_input=outcome_input, now=OUTCOME_AS_OF)
    with pytest.raises(DataValidationError):
        await svc.record_outcome(created["uuid"], outcome_input=outcome_input, now=OUTCOME_AS_OF)


async def test_cancelling_an_already_cancelled_decision_is_rejected(
    db: AsyncEngine, test_settings: Settings
) -> None:
    svc = DecisionJournalService(db, test_settings)
    created = await svc.create_decision(asset="ETH", decision_type="watch", thesis="Just watching.")
    await svc.cancel_decision(created["uuid"])
    with pytest.raises(DataValidationError):
        await svc.cancel_decision(created["uuid"])


async def test_link_and_unlink_paper_trade_round_trip(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    """ "Integration with Paper Trading": a reference only, never an automatic creation in either
    direction."""
    await _seed_btc(market)
    svc = DecisionJournalService(db, test_settings)
    paper_svc = PaperTradingService(db, test_settings)

    decision = await svc.create_decision(
        asset="BTC", decision_type="long_spot", thesis="Thesis.", now=DECISION_AS_OF
    )
    trade = await paper_svc.create_trade(
        asset="BTC", direction="long", notional=Decimal(10_000), now=DECISION_AS_OF
    )

    linked = await svc.link_paper_trade(decision["uuid"], paper_trade_id=trade["uuid"])
    assert linked["paper_trade_id"] is not None

    unlinked = await svc.unlink_paper_trade(decision["uuid"])
    assert unlinked["paper_trade_id"] is None


async def test_linking_an_unknown_paper_trade_is_not_found(
    db: AsyncEngine, test_settings: Settings
) -> None:
    import uuid

    svc = DecisionJournalService(db, test_settings)
    decision = await svc.create_decision(
        asset="ETH", decision_type="watch", thesis="Just watching."
    )
    with pytest.raises(NotFoundError):
        await svc.link_paper_trade(decision["uuid"], paper_trade_id=uuid.uuid4())


async def test_relevant_alert_ids_capture_active_alerts_at_decision_time(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """ "Integration with Alerts and Briefs": alert IDs are captured once, as context, never
    auto-converted into a decision and never refreshed afterward."""
    alert_repo = AlertRepository(db)
    _alert_id, alert_uuid = await alert_repo.insert_alert(
        now=DECISION_AS_OF,
        alert_type="divergence",
        severity="medium",
        domain="BTC",
        dedup_key="test-journal-alert-key",
        trigger_condition="test condition",
        observed_value="1",
        reference_value=None,
        evidence_field_ids=[],
        snapshot_id=None,
        source_tool_id="test",
        component_status="ok",
        data_quality_state="ok",
    )
    svc = DecisionJournalService(db, test_settings)
    decision = await svc.create_decision(
        asset="BTC", decision_type="long_spot", thesis="Thesis.", now=DECISION_AS_OF
    )
    assert str(alert_uuid) in decision["relevant_alert_ids"]


async def test_missing_market_data_still_creates_a_decision_with_no_observed_price(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """No bars seeded for BTC — the service must say "insufficient data" via a ``None`` field,
    never guess a price (R3). Unlike paper trading, a journal entry does not require a price at
    all, so creation itself must still succeed."""
    svc = DecisionJournalService(db, test_settings)
    row = await svc.create_decision(
        asset="BTC", decision_type="long_spot", thesis="Thesis.", now=DECISION_AS_OF
    )
    assert row["observed_price_at_decision"] is None


async def test_review_and_stats_reflect_actual_recorded_decisions(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed_btc(market)
    svc = DecisionJournalService(db, test_settings)
    await svc.create_decision(
        asset="BTC", decision_type="long_spot", thesis="Thesis one.", now=DECISION_AS_OF
    )
    await svc.create_decision(
        asset="BTC", decision_type="long_spot", thesis="Thesis two.", now=DECISION_AS_OF
    )
    stats = await svc.stats()
    assert stats.total_decisions == 2
    assert stats.open_decisions == 2
    review = await svc.review()
    assert review.decisions_by_type.get("long_spot") == 2


async def test_get_unknown_decision_is_not_found(db: AsyncEngine, test_settings: Settings) -> None:
    import uuid

    svc = DecisionJournalService(db, test_settings)
    with pytest.raises(NotFoundError):
        await svc.get_decision(uuid.uuid4())


async def test_update_notes_touches_only_the_notes_field(
    db: AsyncEngine, test_settings: Settings
) -> None:
    svc = DecisionJournalService(db, test_settings)
    created = await svc.create_decision(
        asset="ETH",
        decision_type="watch",
        thesis="Original thesis.",
        notes="first note",
    )
    updated = await svc.update_notes(created["uuid"], notes="second note")
    assert updated["notes"] == "second note"
    assert updated["thesis"] == "Original thesis."
    assert updated["decision_snapshot_id"] == created["decision_snapshot_id"]


async def test_data_provenance_decision_snapshot_is_reproducible(
    market: MarketHarness, db: AsyncEngine, test_settings: Settings
) -> None:
    """Every journal entry's decision-time evidence is traceable back to a stored, hashed
    ``ai.snapshot`` row — the same reproducibility guarantee Phase 21 already provides."""
    await _seed_btc(market)
    svc = DecisionJournalService(db, test_settings)
    created = await svc.create_decision(
        asset="BTC", decision_type="long_spot", thesis="Thesis.", now=DECISION_AS_OF
    )
    repo = DecisionJournalRepository(db)
    row = await repo.get_by_uuid(created["uuid"])
    assert row is not None
    assert row["decision_snapshot_id"] == created["decision_snapshot_id"]
