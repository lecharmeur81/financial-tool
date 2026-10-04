"""Read-only intelligence-event API endpoints against real PostgreSQL (Phase 35): the list/detail
round trip, and the filters each query parameter promises. Same ``TestClient`` harness convention
as ``test_paper_api.py``. Runs wherever a real test database is reachable."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.repository import AlertRepository
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.realtime.repository import IntelligenceEventRepository
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

AS_OF = datetime(2026, 10, 4, tzinfo=UTC)


def get(settings: Settings, path: str, params: dict[str, Any] | None = None) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params=params or {})
    return response.status_code, response.json()


async def _seed(db: AsyncEngine, *, domain: str) -> None:
    """``sig.intelligence_event.alert_id`` is a real foreign key into ``usr.alert_event``, so a
    legitimate alert row is created first (via ``AlertRepository.insert_alert``, the same helper
    ``test_alerts_service.py`` already uses) and its actual database id is used — never a
    fabricated one."""
    alerts = AlertRepository(db)
    alert_db_id, _alert_uuid = await alerts.insert_alert(
        now=AS_OF,
        alert_type="anomaly",
        severity="critical",
        domain=domain,
        dedup_key=f"anomaly:{domain}_funding",
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
    inserted = await repo.insert_event(
        now=AS_OF,
        observed_at=AS_OF,
        domain=domain,
        event_type="anomaly",
        severity="critical",
        previous_value=None,
        current_value="extreme_high",
        change_magnitude=None,
        detection_method="cfi.alerts.rules.evaluate_anomaly",
        data_quality_state="ok",
        component_status="ok",
        dedup_key=f"anomaly:{domain}_funding",
        correlation_key="snapshot:1",
        snapshot_id=None,
        alert_id=alert_db_id,
    )
    assert inserted is not None


async def test_list_returns_the_seeded_event_with_full_provenance(
    db: AsyncEngine, test_settings: Settings
) -> None:
    await _seed(db, domain="BTC")
    status, body = get(test_settings, "/api/v1/intelligence-events/")
    assert status == 200
    assert len(body) == 1
    event = body[0]
    assert event["domain"] == "BTC"
    assert event["event_type"] == "anomaly"
    assert event["severity"] == "critical"
    assert event["current_value"] == "extreme_high"
    assert event["detection_method"] == "cfi.alerts.rules.evaluate_anomaly"
    assert event["status"] == "new"


async def test_list_filters_by_domain(db: AsyncEngine, test_settings: Settings) -> None:
    await _seed(db, domain="BTC")
    await _seed(db, domain="ETH")
    status, body = get(test_settings, "/api/v1/intelligence-events/", params={"domain": "ETH"})
    assert status == 200
    assert len(body) == 1
    assert body[0]["domain"] == "ETH"


async def test_get_one_by_id_round_trips(db: AsyncEngine, test_settings: Settings) -> None:
    await _seed(db, domain="BTC")
    _, listed = get(test_settings, "/api/v1/intelligence-events/")
    event_id = listed[0]["event_id"]
    status, body = get(test_settings, f"/api/v1/intelligence-events/{event_id}")
    assert status == 200
    assert body["event_id"] == event_id


async def test_get_one_by_unknown_id_is_a_404(db: AsyncEngine, test_settings: Settings) -> None:
    import uuid

    status, body = get(test_settings, f"/api/v1/intelligence-events/{uuid.uuid4()}")
    assert status == 404
    assert body["error_code"] == "not_found"
