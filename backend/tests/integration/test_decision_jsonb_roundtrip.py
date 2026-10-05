"""Phase 38.3: the decision-input hash and the producer payload hash across a *real* PostgreSQL
JSONB round trip. A snapshot payload is stored with the platform's own ``insert_snapshot`` (so the
production JSON serializer and the ``jsonb`` column are both exercised), read back, and the
Phase 38.2 hash, the Phase 21 producer hash and the whole Decision Context are compared.

Skipped unless the integration services are configured (``CFI_DATABASE_URL`` and ``CFI_REDIS_URL``).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.analyst.repository import AnalystRepository
from cfi.core.config import Settings
from cfi.decision.context import build_decision_context
from cfi.decision.identity import HashCheck, SnapshotRef, decision_input_hash, producer_payload_hash
from tests.decision_snapshots import build_real_snapshot
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]


@pytest.mark.parametrize("scope", ["BTC", "SOL"])
async def test_hashes_and_context_survive_the_jsonb_round_trip(
    db: AsyncEngine, monkeypatch: pytest.MonkeyPatch, settings: Settings, scope: str
) -> None:
    codes = ["S2", "S1", "N", "S1", "S2"] if scope == "BTC" else ["S2", "S1", "N", "S1"]
    snap = await build_real_snapshot(monkeypatch, settings, codes, scope=scope, question="q")
    live = snap.payload()
    repo = AnalystRepository(db)
    row_id, row_uuid = await repo.insert_snapshot(
        created_at=snap.created_at,
        as_of=snap.as_of,
        knowledge_time=snap.knowledge_time,
        snapshot_version=snap.snapshot_version,
        payload=live,
        payload_hash=snap.snapshot_id,
    )
    async with db.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT payload, payload_hash, uuid, created_at FROM ai.snapshot WHERE id = :i"
                ),
                {"i": row_id},
            )
        ).one()
    stored, stored_hash, stored_uuid, created_at = row
    assert stored_hash == snap.snapshot_id
    assert producer_payload_hash(stored) == stored_hash
    assert decision_input_hash(stored) == decision_input_hash(live)

    ref = SnapshotRef(
        row_id=row_id, uuid=str(stored_uuid), payload_hash=stored_hash, created_at=created_at
    )
    from_db = build_decision_context(stored, scope, snapshot_ref=ref)
    from_live = build_decision_context(live, scope)
    assert from_db.identity.producer_hash_check is HashCheck.VERIFIED
    assert from_db.identity.row_id == row_id
    assert str(from_db.identity.uuid) == str(row_uuid)
    assert from_db.assessment == from_live.assessment
