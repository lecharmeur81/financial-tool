"""``GET /api/v1/intelligence/snapshot`` against real PostgreSQL (Phase 44): the latest stored
snapshot is read back through the real repository and served with its identity; an empty table is
a 404; the read path never writes. Skipped unless the integration services are configured."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.analyst.repository import AnalystRepository
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from tests.decision_live_payload import live_state_payload
from tests.decision_snapshots import stored_form
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

PATH = "/api/v1/intelligence/snapshot"


def _get(settings: Settings) -> tuple[int, dict[str, object]]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(PATH)
    return response.status_code, response.json()


async def _store(db: AsyncEngine, payload: dict[str, object]) -> tuple[int, str]:
    stored = stored_form(payload)
    now = datetime.now(UTC)
    row_id, row_uuid = await AnalystRepository(db).insert_snapshot(
        created_at=now,
        as_of=now,
        knowledge_time=now,
        snapshot_version="analyst_snapshot.v1",
        payload=stored,
        payload_hash=producer_payload_hash(stored),
    )
    return row_id, str(row_uuid)


async def test_no_snapshot_is_a_404(db: AsyncEngine, test_settings: Settings) -> None:
    status, body = _get(test_settings)
    assert status == 404
    assert body["error_code"] == "not_found"


async def test_the_latest_stored_snapshot_is_served_with_its_identity(
    db: AsyncEngine, test_settings: Settings
) -> None:
    older = live_state_payload()
    older["as_of"] = "2026-10-05T10:00:00+00:00"
    older["knowledge_time"] = "2026-10-05T10:00:00+00:00"
    await _store(db, older)
    row_id, row_uuid = await _store(db, live_state_payload())

    status, body = _get(test_settings)
    assert status == 200
    assert body["contract_version"] == "unified_snapshot.v0"
    snap = body["snapshot"]
    assert isinstance(snap, dict)
    assert snap["row_id"] == row_id
    assert snap["uuid"] == row_uuid
    assert snap["producer_hash_check"] == "verified"  # survives the JSONB round trip
    assert snap["as_of"] == "2026-10-05T23:09:52.212066+00:00"
    assert isinstance(body["global_domains"], list)
    assets = body["assets"]
    assert isinstance(assets, dict)
    assert set(assets) == {"BTC", "ETH", "SOL", "XRP"}


async def test_an_unsupported_stored_payload_is_a_503_not_a_crash(
    db: AsyncEngine, test_settings: Settings
) -> None:
    payload = live_state_payload()
    payload["snapshot_version"] = "analyst_snapshot.v0"
    await _store(db, payload)
    status, _ = _get(test_settings)
    assert status == 503


async def test_the_read_path_does_not_write(db: AsyncEngine, test_settings: Settings) -> None:
    await _store(db, live_state_payload())
    async with db.connect() as conn:
        before = (await conn.execute(text("select count(*) from ai.snapshot"))).scalar_one()
    status, _ = _get(test_settings)
    assert status == 200
    async with db.connect() as conn:
        after = (await conn.execute(text("select count(*) from ai.snapshot"))).scalar_one()
    assert after == before
