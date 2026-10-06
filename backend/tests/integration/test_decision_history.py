"""``GET /api/v1/decision/history`` against real PostgreSQL (Phase 41).

Snapshots are stored through the platform's own ``insert_snapshot`` (so Phase 40 persists their
assessments exactly as in production) and the history is read back through the real repository and
route. Pinned here: previous/current pairing by ``snapshot_id``, scope isolation, the explicit
no-history and version-change states, ``out_of_order_as_of``, API == the pure comparison, the
read path never writes, and ``/decision/current`` is unchanged and consistent. Runs only in the
isolated ``_test`` database (``tests/integration/conftest.py``)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.analyst.repository import AnalystRepository
from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.decision_history import DecisionHistoryRepository, build_history
from tests.decision_history_builders import BASE_TIME, stored_snapshot
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

PATH = "/api/v1/decision/history"
BULLISH = ["S1", "S1", "S1", "S1", "S1"]
THIN = ["S1", "S1", "S1", "U", "U"]
BEARISH = ["A2", "A2", "A2", "A2", "A2"]


def _get(
    settings: Settings, params: dict[str, Any] | None = None, path: str = PATH
) -> tuple[int, dict[str, Any]]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params=params or {})
    return response.status_code, response.json()


async def _store(
    db: AsyncEngine, codes: Sequence[str], *, as_of: datetime | None = None, **context: Any
) -> int:
    """Store one snapshot through ``insert_snapshot``; returns its ``ai.snapshot.id``."""
    n = int(await _scalar(db, "select coalesce(max(id), 0) from ai.snapshot"))
    snap = stored_snapshot(codes, snapshot_id=n + 1, as_of=as_of, **context)
    row_id, _ = await AnalystRepository(db).insert_snapshot(
        created_at=datetime.now(UTC),
        as_of=snap.as_of,
        knowledge_time=snap.knowledge_time,
        snapshot_version="analyst_snapshot.v1",
        payload=snap.payload,
        payload_hash=snap.payload_hash,
    )
    return row_id


async def _scalar(db: AsyncEngine, sql: str, **params: Any) -> Any:
    async with db.connect() as conn:
        return (await conn.execute(text(sql), params)).scalar_one()


async def _exec(db: AsyncEngine, sql: str, **params: Any) -> None:
    async with db.begin() as conn:
        await conn.execute(text(sql), params)


async def test_no_persisted_assessment_is_a_404(db: AsyncEngine, test_settings: Settings) -> None:
    status, body = _get(test_settings)
    assert status == 404
    assert body["error_code"] == "not_found"


async def test_the_first_assessment_returns_the_explicit_no_history_state(
    db: AsyncEngine, test_settings: Settings
) -> None:
    row_id = await _store(db, BULLISH)
    status, body = _get(test_settings)
    assert status == 200
    assert body["contract_version"] == "decision_history.v0"
    assert body["asset"] == "BTC"
    assert body["ordering"] == "snapshot_id"
    current = body["current"]
    assert current["snapshot_id"] == row_id
    assert current["state"] == "No Previous Assessment"
    assert current["change"] is None
    assert current["previous_snapshot_id"] is None
    assert body["returned"] == 1


async def test_current_is_compared_with_the_previous_assessment_in_snapshot_order(
    db: AsyncEngine, test_settings: Settings
) -> None:
    first = await _store(db, BULLISH)
    second = await _store(db, THIN)
    status, body = _get(test_settings)
    assert status == 200
    current = body["current"]
    assert current["snapshot_id"] == second
    assert current["previous_snapshot_id"] == first
    assert current["state"] == "Compared"
    change = current["change"]
    assert change["classification"] == "MULTIPLE_CHANGES"
    assert change["coverage"]["previous"]["available"] == 5
    assert change["coverage"]["current"]["available"] == 3
    assert change["coverage"]["directional_became_unavailable"] == ["macro", "market_structure"]
    assert [e["snapshot_id"] for e in body["history"]] == [second, first]
    assert body["history"][1]["state"] == "No Previous Assessment"


async def test_identical_consecutive_assessments_are_no_change(
    db: AsyncEngine, test_settings: Settings
) -> None:
    await _store(db, BULLISH)
    await _store(db, BULLISH)
    _, body = _get(test_settings)
    assert body["current"]["change"]["classification"] == "NO_CHANGE"
    assert body["current"]["change"]["changed_dimensions"] == []


async def test_the_api_equals_the_pure_comparison_of_the_persisted_rows(
    db: AsyncEngine, test_settings: Settings
) -> None:
    for codes in (BULLISH, THIN, BEARISH, BULLISH):
        await _store(db, codes)
    rows = await DecisionHistoryRepository(db).recent_for_scope("BTC", count=11)
    expected = [e.to_dict() for e in build_history(rows, limit=10)]
    status, body = _get(test_settings)
    assert status == 200
    assert body["history"] == json.loads(json.dumps(expected))
    assert body["current"] == body["history"][0]


async def test_limit_returns_the_newest_entries_and_the_oldest_still_has_its_predecessor(
    db: AsyncEngine, test_settings: Settings
) -> None:
    ids = [await _store(db, c) for c in (BULLISH, THIN, BULLISH, BEARISH)]
    status, body = _get(test_settings, {"limit": 2})
    assert status == 200
    assert body["limit"] == 2
    assert body["returned"] == 2
    assert [e["snapshot_id"] for e in body["history"]] == [ids[3], ids[2]]
    assert body["history"][1]["state"] == "Compared"
    assert body["history"][1]["previous_snapshot_id"] == ids[1]


async def test_the_latest_persisted_assessment_is_the_latest_snapshot_and_matches_decision_current(
    db: AsyncEngine, test_settings: Settings
) -> None:
    for codes in (BULLISH, THIN, BEARISH):
        last = await _store(db, codes)
    _, hist = _get(test_settings, {"asset": "BTC"})
    status, cur = _get(test_settings, {"asset": "BTC"}, path="/api/v1/decision/current")
    assert status == 200
    assert hist["current"]["snapshot_id"] == last == cur["snapshot"]["row_id"]
    assert hist["current"]["stance"] == cur["stance"]["final"]
    assert hist["current"]["decision_input_hash"] == cur["snapshot"]["decision_input_hash"]
    assert cur["contract_version"] == "decision_view.v0"  # the Phase 39 contract is untouched


async def test_history_is_isolated_by_scope(db: AsyncEngine, test_settings: Settings) -> None:
    first = await _store(db, BULLISH)
    second = await _store(db, THIN)
    # BTC has no row for the newest snapshot; ETH/SOL/XRP still do.
    await _exec(
        db,
        "delete from sig.decision_assessment where snapshot_id = :sid and scope = 'BTC'",
        sid=second,
    )
    _, btc = _get(test_settings, {"asset": "BTC"})
    assert btc["current"]["snapshot_id"] == first
    assert btc["current"]["state"] == "No Previous Assessment"  # never ETH/SOL/XRP's row 2
    assert btc["returned"] == 1
    for asset in ("ETH", "SOL", "XRP"):
        _, other = _get(test_settings, {"asset": asset})
        assert other["asset"] == asset
        assert [e["snapshot_id"] for e in other["history"]] == [second, first]
        assert other["current"]["state"] == "Compared"


async def test_each_scope_has_its_own_history(db: AsyncEngine, test_settings: Settings) -> None:
    await _store(db, BULLISH)
    await _store(db, BEARISH)
    for asset in ("BTC", "ETH", "SOL", "XRP"):
        status, body = _get(test_settings, {"asset": asset})
        assert status == 200
        assert body["returned"] == 2
        scopes = await _scalar(
            db,
            "select string_agg(distinct scope, ',') from sig.decision_assessment "
            "where snapshot_id = any(:ids)",
            ids=[e["snapshot_id"] for e in body["history"]],
        )
        assert scopes == "BTC,ETH,SOL,XRP"


async def test_a_different_parameter_version_is_not_comparable(
    db: AsyncEngine, test_settings: Settings
) -> None:
    first = await _store(db, BULLISH)
    second = await _store(db, THIN)
    await _exec(
        db,
        "update sig.decision_assessment set parameter_version = 'decision_params.v-older' "
        "where snapshot_id = :sid and scope = 'BTC'",
        sid=first,
    )
    _, body = _get(test_settings)
    current = body["current"]
    assert current["snapshot_id"] == second
    assert current["state"] == "Not Comparable (version change)"
    assert current["change"] is None
    assert current["previous_parameter_version"] == "decision_params.v-older"
    assert current["previous_methodology_version"] == current["methodology_version"]
    # the other scopes are unaffected
    _, eth = _get(test_settings, {"asset": "ETH"})
    assert eth["current"]["state"] == "Compared"


async def test_a_template_version_difference_alone_is_still_compared(
    db: AsyncEngine, test_settings: Settings
) -> None:
    first = await _store(db, BULLISH)
    await _store(db, THIN)
    await _exec(
        db,
        "update sig.decision_assessment set template_version = 'decision_templates.v-older' "
        "where snapshot_id = :sid and scope = 'BTC'",
        sid=first,
    )
    _, body = _get(test_settings)
    assert body["current"]["state"] == "Compared"


async def test_a_back_dated_snapshot_is_ordered_by_snapshot_id_and_flagged(
    db: AsyncEngine, test_settings: Settings
) -> None:
    later_as_of = BASE_TIME + timedelta(hours=6)
    first = await _store(db, BULLISH, as_of=later_as_of)
    second = await _store(db, THIN, as_of=BASE_TIME)  # recorded second, earlier as_of
    _, body = _get(test_settings)
    current = body["current"]
    assert current["snapshot_id"] == second  # ordering never follows as_of
    assert current["previous_snapshot_id"] == first
    assert current["out_of_order_as_of"] is True
    assert current["snapshot_as_of"] == BASE_TIME.isoformat()  # reported exactly as stored
    assert body["history"][1]["snapshot_as_of"] == later_as_of.isoformat()
    assert body["history"][1]["out_of_order_as_of"] is False
    # and /decision/current agrees on which snapshot is current
    _, cur = _get(test_settings, path="/api/v1/decision/current")
    assert cur["snapshot"]["row_id"] == second


async def test_unsupported_asset_and_bad_limits_are_422(
    db: AsyncEngine, test_settings: Settings
) -> None:
    await _store(db, BULLISH)
    assert _get(test_settings, {"asset": "DOGE"})[0] == 422
    assert _get(test_settings, {"asset": "market"})[0] == 422
    assert _get(test_settings, {"limit": 0})[0] == 422
    assert _get(test_settings, {"limit": 101})[0] == 422
    assert _get(test_settings, {"limit": 100})[0] == 200


async def test_the_read_path_does_not_write(db: AsyncEngine, test_settings: Settings) -> None:
    for codes in (BULLISH, THIN):
        await _store(db, codes)
    sql = (
        "select (select count(*) from ai.snapshot) || ':'"
        " || (select count(*) from sig.decision_assessment) || ':'"
        " || coalesce((select md5(string_agg(decision_input_hash || stance, ',' order by id))"
        " from sig.decision_assessment), '')"
    )
    before = await _scalar(db, sql)
    for asset in ("BTC", "ETH", "SOL", "XRP"):
        assert _get(test_settings, {"asset": asset})[0] == 200
    assert await _scalar(db, sql) == before


async def test_a_corrupt_persisted_row_is_a_503_not_a_guess(
    db: AsyncEngine, test_settings: Settings
) -> None:
    await _store(db, BULLISH)
    second = await _store(db, THIN)
    await _exec(
        db,
        "update sig.decision_assessment set assessment = assessment #- '{assessment,risks}' "
        "where snapshot_id = :sid and scope = 'BTC'",
        sid=second,
    )
    status, body = _get(test_settings)
    assert status == 503
    assert "cannot be compared" in body["detail"]
