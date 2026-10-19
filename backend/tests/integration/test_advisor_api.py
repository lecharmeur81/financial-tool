"""``GET /api/v1/advisor/brief`` against real PostgreSQL (Phase 53): a payload stored with the
platform's own ``insert_snapshot`` is read back through the real repository query and composed into
``advisor_brief.v0``. Runs only on the isolated ``<configured name>_test`` database (see
``conftest.py``). Asserts the contract and the identity of the answer, not the market view: the
stance, the data gaps and the decision state depend on the stored snapshot and are not assumed.
Skipped unless the integration services are configured."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.advisor import NOT_CLAIMED
from cfi.analyst.repository import AnalystRepository
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.decision.identity import producer_payload_hash
from tests.decision_live_payload import live_state_payload
from tests.decision_snapshots import stored_form
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

PATH = "/api/v1/advisor/brief"

TOP_LEVEL_FIELDS = {
    "contract_version",
    "asset",
    "answered_from",
    "snapshot",
    "layers",
    "assessment",
    "signals",
    "readings",
    "uncertainty",
    "data_gaps",
    "risk",
    "invalidation",
    "reassessment",
    "field_trace",
    "not_claimed",
}


def _get(settings: Settings, params: dict[str, str] | None = None) -> tuple[int, dict[str, object]]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(PATH, params=params or {})
    return response.status_code, response.json()


async def _store(db: AsyncEngine) -> tuple[int, str]:
    stored = stored_form(live_state_payload())
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


async def _snapshot_count(db: AsyncEngine) -> int:
    async with db.connect() as conn:
        return int((await conn.execute(text("select count(*) from ai.snapshot"))).scalar_one())


async def test_no_stored_snapshot_is_a_404(db: AsyncEngine, test_settings: Settings) -> None:
    status, body = _get(test_settings, {"asset": "BTC"})
    assert status == 404
    assert body["error_code"] == "not_found"
    assert "contract_version" not in body


async def test_a_stored_snapshot_is_served_as_a_btc_brief(
    db: AsyncEngine, test_settings: Settings
) -> None:
    row_id, row_uuid = await _store(db)

    status, body = _get(test_settings, {"asset": "BTC"})

    assert status == 200
    assert set(body) == TOP_LEVEL_FIELDS
    assert body["contract_version"] == "advisor_brief.v0"
    assert body["asset"] == "BTC"
    snapshot = body["snapshot"]
    assert isinstance(snapshot, dict)
    assert snapshot["row_id"] == row_id
    assert snapshot["uuid"] == row_uuid

    assessment = body["assessment"]
    assert isinstance(assessment, dict)
    stance = assessment["stance"]
    assert isinstance(stance, dict)
    for key in ("final", "confidence", "posture"):
        assert isinstance(stance[key], str)
        assert stance[key]
    state = assessment["investment_state"]
    assert isinstance(state, dict)
    assert isinstance(state["decision_state"], str)
    assert state["decision_state"]

    # Collections keep their shape whether or not the snapshot is complete.
    for key in ("signals", "readings", "reassessment"):
        assert isinstance(body[key], list)
    data_gaps = body["data_gaps"]
    assert isinstance(data_gaps, dict)
    assert isinstance(data_gaps["has_gaps"], bool)
    assert isinstance(data_gaps["items"], list)
    assert data_gaps["has_gaps"] == bool(data_gaps["items"])

    # The disclaimers are part of the contract and travel with every brief.
    assert body["not_claimed"] == [dict(n) for n in NOT_CLAIMED]


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP"])
async def test_every_supported_asset_is_briefed_from_the_same_snapshot(
    db: AsyncEngine, test_settings: Settings, asset: str
) -> None:
    row_id, _ = await _store(db)
    status, body = _get(test_settings, {"asset": asset})
    assert status == 200
    assert body["asset"] == asset
    snapshot = body["snapshot"]
    assert isinstance(snapshot, dict)
    assert snapshot["row_id"] == row_id


async def test_an_unsupported_asset_is_a_422_with_no_brief(
    db: AsyncEngine, test_settings: Settings
) -> None:
    await _store(db)
    status, body = _get(test_settings, {"asset": "DOGE"})
    assert status == 422
    assert "contract_version" not in body


async def test_the_read_path_does_not_write(db: AsyncEngine, test_settings: Settings) -> None:
    await _store(db)
    before = await _snapshot_count(db)
    for asset in ("BTC", "ETH", "SOL", "XRP"):
        status, _ = _get(test_settings, {"asset": asset})
        assert status == 200
    assert await _snapshot_count(db) == before == 1
