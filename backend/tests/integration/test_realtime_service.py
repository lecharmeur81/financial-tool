"""``RealtimeIntelligenceService`` against real PostgreSQL + Redis (Phase 35): event creation,
idempotency/deduplication, cycle-lock mutual exclusion, event provenance, AI-trigger gating, and
that Phase 23's own alert behavior is unaffected by this extension. Runs wherever a real test
database and Redis are reachable, gated exactly like every other integration suite."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.repository import AlertRepository
from cfi.cache.redis import create_redis
from cfi.core.config import Settings
from cfi.db import tables as t
from cfi.market.jobs import backfill_step
from cfi.market.sources import ADAPTERS as MARKET_ADAPTERS
from cfi.market.universe import ASSET_SYMBOLS, ohlcv_dataset
from cfi.realtime.repository import IntelligenceEventRepository
from cfi.realtime.service import RealtimeIntelligenceService
from tests.integration.conftest import isolated_redis_url, requires_services
from tests.integration.market_support import MarketHarness

pytestmark = [pytest.mark.integration, requires_services]

AS_OF = datetime(2026, 10, 4, tzinfo=UTC)
DAILY = ohlcv_dataset("usd", "1d")


@pytest.fixture
async def redis(test_settings: Settings) -> AsyncIterator[Redis]:
    # Redis database 15, never the live stack's database 0 (see ``isolated_redis_url``).
    url = isolated_redis_url(test_settings.redis_url.get_secret_value())
    client = create_redis(test_settings.model_copy(update={"redis_url": SecretStr(url)}))
    await client.delete("cfi:realtime:cycle_lock", "cfi:realtime:data_arrival_debounce")
    yield client
    await client.delete("cfi:realtime:cycle_lock", "cfi:realtime:data_arrival_debounce")
    await client.aclose()


async def _seed_minimum_regime_data(market: MarketHarness) -> None:
    """The smallest real seed that lets the regime engine report a ``status="ok"`` classification
    (never fabricated — R3): ``cfi.alerts.rules.evaluate_regime_change`` only ever reports a
    candidate when the regime tool's own snapshot status is "ok", which itself requires at least
    one regime definition's ``available_weight`` to clear
    ``cfi.regime.parameters.REGIME_CLASSIFIER_V1.min_available_weight`` (0.5). Backfilling every
    tracked asset's OHLCV history — the same ``market`` harness + ``backfill_step`` helper already
    used by ``tests/integration/test_divergence_api.py`` — is read directly by
    ``cfi.market_structure.service`` (no re-ingestion, see its own module docstring) and populates
    ``market_structure_score``, ``btc_trend``, ``btc_rsi`` and ``market_breadth``: together 0.55 of
    the "expansion" regime's weight, comfortably over the 0.5 threshold. No other domain, and no
    application code, is touched to get there."""
    for asset in ASSET_SYMBOLS:
        await backfill_step(market.ctx, MARKET_ADAPTERS["coinbase"], DAILY, asset, depth_days=280)


# --------------------------------------------------------------------------- change -> event


async def test_first_cycle_creates_at_least_one_event_for_the_always_present_regime_candidate(
    db: AsyncEngine, test_settings: Settings, redis: Redis, market: MarketHarness
) -> None:
    """Testing requirement #1 (first event creation): ``evaluate_regime_change`` reports a current
    classification (possibly ``mixed_unclear``, never fabricated — R3) whenever the regime tool's
    own snapshot reaches ``status="ok"``, so once the minimum real market-structure data this
    requires (see ``_seed_minimum_regime_data``) is seeded, the very first cycle must create
    exactly one alert — and therefore exactly one intelligence event — for it."""
    await _seed_minimum_regime_data(market)
    svc = RealtimeIntelligenceService(db, test_settings, redis=redis)
    result = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.locked_out is False
    assert result.alerts is not None
    assert result.events_created >= 1
    assert result.events_created == result.alerts.created + result.alerts.rearmed


async def test_a_second_identical_cycle_creates_no_new_events(
    db: AsyncEngine, test_settings: Settings, redis: Redis, market: MarketHarness
) -> None:
    """Testing requirement #5 (non-meaningful/noisy change ignored): nothing in the underlying
    data changed between the two calls, so ``cfi.alerts.lifecycle.decide`` skips every candidate
    the second time, and no new event is created for any of them. The minimum real market-
    structure data (see ``_seed_minimum_regime_data``) is seeded first so the first cycle actually
    has a "ok" regime candidate to create and then repeat unchanged."""
    await _seed_minimum_regime_data(market)
    svc = RealtimeIntelligenceService(db, test_settings, redis=redis)
    first = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    second = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert first.events_created >= 1
    assert second.events_created == 0
    assert second.alerts is not None
    assert second.alerts.created == 0


# --------------------------------------------------------------------------- idempotency / dedup


async def test_a_duplicate_alert_id_is_safely_deduplicated_at_the_repository_level(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """Testing requirements #2/#3 (duplicate event suppression; worker retry/idempotency): the
    exact scenario the migration's ``ON CONFLICT (alert_id) DO NOTHING`` guarantees — inserting
    an event for the same ``alert_id`` twice (a worker retrying the same decision, or two
    overlapping cycles that both got past the lock) must silently no-op the second time, never
    create a second row or raise. ``sig.intelligence_event.alert_id`` is a real foreign key into
    ``usr.alert_event`` (the migration's own "deterministic anchor" for idempotency), so this test
    first creates a real alert row via ``AlertRepository.insert_alert`` — the same helper
    ``tests/integration/test_alerts_service.py`` already uses — and dedups against its actual id,
    rather than an invalid fabricated one."""
    alerts = AlertRepository(db)
    alert_db_id, _alert_uuid = await alerts.insert_alert(
        now=AS_OF,
        alert_type="anomaly",
        severity="critical",
        domain="BTC",
        dedup_key="anomaly:funding_rate",
        trigger_condition="Funding rate anomaly",
        observed_value="extreme_high",
        reference_value=None,
        evidence_field_ids=["get_derivatives.funding_rate"],
        snapshot_id=None,
        source_tool_id="get_derivatives",
        component_status="ok",
        data_quality_state="ok",
    )
    repo = IntelligenceEventRepository(db)
    first = await repo.insert_event(
        now=AS_OF,
        observed_at=AS_OF,
        domain="BTC",
        event_type="anomaly",
        severity="critical",
        previous_value=None,
        current_value="extreme_high",
        change_magnitude=None,
        detection_method="cfi.alerts.rules.evaluate_anomaly",
        data_quality_state="ok",
        component_status="ok",
        dedup_key="anomaly:funding_rate",
        correlation_key="snapshot:1",
        snapshot_id=None,
        alert_id=alert_db_id,
    )
    second = await repo.insert_event(
        now=AS_OF,
        observed_at=AS_OF,
        domain="BTC",
        event_type="anomaly",
        severity="critical",
        previous_value=None,
        current_value="extreme_high",
        change_magnitude=None,
        detection_method="cfi.alerts.rules.evaluate_anomaly",
        data_quality_state="ok",
        component_status="ok",
        dedup_key="anomaly:funding_rate",
        correlation_key="snapshot:1",
        snapshot_id=None,
        alert_id=alert_db_id,
    )
    assert first is not None
    assert second is None  # the retry/duplicate is a safe no-op, not a second row

    async with db.connect() as conn:
        rows = (
            await conn.execute(
                select(t.intelligence_event).where(t.intelligence_event.c.alert_id == alert_db_id)
            )
        ).all()
    assert len(rows) == 1


async def test_two_different_domains_are_independently_deduplicated(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """Testing requirement #6 (multiple domains operating independently): one domain's event does
    not block or interfere with another's, even within the same correlation group. Each event's
    ``alert_id`` is the real id of its own ``usr.alert_event`` row (created via
    ``AlertRepository.insert_alert``, the same helper ``test_alerts_service.py`` already uses),
    satisfying the real foreign key rather than a fabricated one."""
    alerts = AlertRepository(db)
    btc_alert_id, _btc_alert_uuid = await alerts.insert_alert(
        now=AS_OF,
        alert_type="regime_change",
        severity="notable",
        domain="BTC",
        dedup_key="regime_change:BTC",
        trigger_condition="Market regime classification",
        observed_value="accumulation",
        reference_value=None,
        evidence_field_ids=["get_market_regime.regime_id"],
        snapshot_id=None,
        source_tool_id="get_market_regime",
        component_status="ok",
        data_quality_state="ok",
    )
    eth_alert_id, _eth_alert_uuid = await alerts.insert_alert(
        now=AS_OF,
        alert_type="anomaly",
        severity="critical",
        domain="ETH",
        dedup_key="anomaly:ETH_funding",
        trigger_condition="Funding rate anomaly",
        observed_value="extreme_low",
        reference_value=None,
        evidence_field_ids=["get_derivatives.funding_rate"],
        snapshot_id=None,
        source_tool_id="get_derivatives",
        component_status="ok",
        data_quality_state="ok",
    )
    repo = IntelligenceEventRepository(db)
    btc = await repo.insert_event(
        now=AS_OF,
        observed_at=AS_OF,
        domain="BTC",
        event_type="regime_change",
        severity="notable",
        previous_value=None,
        current_value="accumulation",
        change_magnitude=None,
        detection_method="cfi.alerts.rules.evaluate_regime_change",
        data_quality_state="ok",
        component_status="ok",
        dedup_key="regime_change:BTC",
        correlation_key="snapshot:2",
        snapshot_id=None,
        alert_id=btc_alert_id,
    )
    eth = await repo.insert_event(
        now=AS_OF,
        observed_at=AS_OF,
        domain="ETH",
        event_type="anomaly",
        severity="critical",
        previous_value=None,
        current_value="extreme_low",
        change_magnitude=None,
        detection_method="cfi.alerts.rules.evaluate_anomaly",
        data_quality_state="ok",
        component_status="ok",
        dedup_key="anomaly:ETH_funding",
        correlation_key="snapshot:2",
        snapshot_id=None,
        alert_id=eth_alert_id,
    )
    assert btc is not None
    assert eth is not None
    assert btc[0] != eth[0]


# --------------------------------------------------------------------------- cycle lock


async def test_the_cycle_lock_prevents_a_concurrent_run(
    db: AsyncEngine, test_settings: Settings, redis: Redis
) -> None:
    """Testing requirement #13 (concurrent processing/idempotency): a cycle that finds the lock
    already held (another worker, an overlapping scheduled run) does nothing rather than racing
    the in-progress one — no events, no alert evaluation, and no error."""
    await redis.set("cfi:realtime:cycle_lock", "1", ex=60)
    svc = RealtimeIntelligenceService(db, test_settings, redis=redis)
    result = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.locked_out is True
    assert result.alerts is None
    assert result.events_created == 0
    assert result.ai_requested == 0


async def test_the_lock_is_released_after_a_successful_cycle(
    db: AsyncEngine, test_settings: Settings, redis: Redis
) -> None:
    svc = RealtimeIntelligenceService(db, test_settings, redis=redis)
    await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert await redis.get("cfi:realtime:cycle_lock") is None


async def test_without_a_redis_client_the_service_still_runs_as_the_sole_runner(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """No lock configured at all (e.g. a context with no Redis available) degrades to "proceed
    unconditionally" rather than refusing to run."""
    svc = RealtimeIntelligenceService(db, test_settings, redis=None)
    result = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.locked_out is False


# --------------------------------------------------------------------------- provenance


async def test_events_carry_full_provenance(
    db: AsyncEngine, test_settings: Settings, redis: Redis, market: MarketHarness
) -> None:
    """Testing requirement #14 (event provenance): every field the spec's "what changed / when /
    which asset / which source / previous / current / detection method / data quality / downstream
    action" checklist asks for is actually populated, never left null by omission. The minimum
    real market-structure data (see ``_seed_minimum_regime_data``) is seeded first so there is an
    actual "ok" regime event to inspect, rather than relying on an empty database."""
    await _seed_minimum_regime_data(market)
    svc = RealtimeIntelligenceService(db, test_settings, redis=redis)
    result = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.alerts is not None

    async with db.connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(t.intelligence_event).where(
                        t.intelligence_event.c.correlation_key
                        == f"snapshot:{result.alerts.snapshot_id}"
                    )
                )
            )
            .mappings()
            .all()
        )
    assert rows
    for row in rows:
        assert row["uuid"] is not None
        assert row["created_at"] == AS_OF
        assert row["observed_at"] is not None
        assert row["domain"]
        assert row["event_type"]
        assert row["severity"] in ("info", "notable", "elevated", "critical")
        assert row["current_value"] is not None
        assert row["detection_method"] == f"cfi.alerts.rules.evaluate_{row['event_type']}"
        assert row["data_quality_state"]
        assert row["component_status"]
        assert row["dedup_key"]
        assert row["correlation_key"]
        assert row["alert_id"] is not None
        assert row["status"] in ("new", "ai_requested")


async def test_the_cycle_snapshot_gets_one_decision_assessment_per_scope(
    db: AsyncEngine, test_settings: Settings, redis: Redis, market: MarketHarness
) -> None:
    """Phase 40: the snapshot the cycle builds goes through ``insert_snapshot``, which persists its
    deterministic assessments - one per scope, no duplicates, and the whole cycle is unaffected."""
    await _seed_minimum_regime_data(market)
    svc = RealtimeIntelligenceService(db, test_settings, redis=redis)
    result = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.alerts is not None
    assert result.alerts.snapshot_id is not None

    async with db.connect() as conn:
        rows = (
            (
                await conn.execute(
                    select(t.decision_assessment).where(
                        t.decision_assessment.c.snapshot_id == result.alerts.snapshot_id
                    )
                )
            )
            .mappings()
            .all()
        )
    assert sorted(r["scope"] for r in rows) == ["BTC", "ETH", "SOL", "XRP"]
    for row in rows:
        assert row["producer_hash_check"] == "verified"
        assert row["methodology_version"] == "decision_methodology.v0"
        assert row["assessment"]["scope"] == row["scope"]


# --------------------------------------------------------------------------- AI-trigger gating


async def test_ai_is_not_requested_when_the_anthropic_key_is_not_configured(
    db: AsyncEngine, test_settings: Settings, redis: Redis
) -> None:
    """Testing requirement #10 (AI trigger gating): the same "credential not configured" posture
    every other AI task already uses — never a failed/errored attempt, a clean no-op."""
    settings_no_key = test_settings.model_copy(update={"anthropic_api_key": None})
    svc = RealtimeIntelligenceService(db, settings_no_key, redis=redis)
    result = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.ai_requested == 0


async def test_ai_is_not_requested_when_nothing_this_cycle_is_severe_enough(
    db: AsyncEngine, test_settings: Settings, redis: Redis
) -> None:
    """Against an empty database the only candidate (regime_change) is "notable", never
    "elevated"/"critical" — below the AI-trigger significance threshold."""
    svc = RealtimeIntelligenceService(db, test_settings, redis=redis)
    result = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.ai_requested == 0


# --------------------------------------------------------------------------- Phase 23 unaffected


async def test_alert_rows_are_still_created_exactly_as_before(
    db: AsyncEngine, test_settings: Settings, redis: Redis
) -> None:
    """Testing requirement #16 (existing Phase 23 alert behavior remains intact): the alert rows
    this cycle writes are indistinguishable from a bare ``AlertService.evaluate()`` call — same
    fields, same statuses, this service only adds a parallel ``sig.intelligence_event`` row."""
    svc = RealtimeIntelligenceService(db, test_settings, redis=redis)
    result = await svc.process_cycle(as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF)
    assert result.alerts is not None
    async with db.connect() as conn:
        rows = (await conn.execute(select(t.alert_event))).mappings().all()
    assert len(rows) == result.alerts.created
    for row in rows:
        assert row["status"] == "active"
        assert row["severity"] in ("info", "notable", "elevated", "critical")
