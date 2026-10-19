"""Phase 51 gate-off alert listing over real SQL and the real FastAPI HTTP stack (PostgreSQL).

With ``INVESTMENT_ALERT_PERSISTENCE_ENABLED`` hard-coded ``False``, one real
``AlertService.evaluate`` cycle (the investment block included) must leave
``GET /api/v1/alerts/`` unchanged for the ordinary alerts seeded before it, and must add no
``investment_state`` item. Unlike
``test_alert_consumers_gate_off.py`` (in-memory fakes), the rows here are written through the real
``AlertRepository`` and read back through the real ``AlertRepository.list_alerts`` SQL and the real
FastAPI route, response model and JSON serialization (``TestClient``).

Scope: this closes the real-SQL and HTTP-serialization gap for ``GET /api/v1/alerts/`` only. It does
not exercise the dashboard or the frontend rendering, journal or paper consumers, or any gate-on
behavior, and it enables nothing.

**This file must not be run without the same explicit authorization as
``test_investment_alert_snapshot_path.py``.** The shared integration fixture drops and recreates the
database named ``<configured name>_test`` on the configured server. The module therefore reuses that
module's own gate (``evaluate_gate``, unchanged): it is skipped unless the confirmation is exactly
``p51_scratch_test`` and the target is the disposable container (host ``127.0.0.1`` or
``localhost``, port ``55432`` or ``55433``, database ``p51_scratch``, no URL query, no runtime
URL). Then run only this file with ``-m integration``. Never run an unfiltered ``pytest`` while the
service variables are set.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.alerts.repository import AlertRepository
from cfi.alerts.service import AlertService
from cfi.api.app import create_app
from cfi.core.config import Settings
from tests.integration.conftest import requires_services
from tests.integration.test_investment_alert_snapshot_path import evaluate_gate

INVESTMENT_TYPE: Final = "investment_state"
LIST_PATH: Final = "/api/v1/alerts/"
AS_OF: Final = datetime(2026, 10, 3, tzinfo=UTC)
SEED_BASE: Final = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)

# Ordinary alerts of types that a cycle does not auto-resolve (only divergence, anomaly and
# capital_rotation are), with dedup keys unique to this test so no cycle candidate supersedes them.
SEEDS: Final = (
    ("whale_activity", "notable"),
    ("macro", "info"),
    ("regime_change", "elevated"),
    ("whale_activity", "critical"),
    ("macro", "notable"),
)

_GATE = evaluate_gate(os.environ)

pytestmark = [
    pytest.mark.integration,
    requires_services,
    pytest.mark.skipif(
        not _GATE.ok,
        reason=(
            "Phase 51 database gate not satisfied (failed checks: "
            f"{', '.join(_GATE.failures) or 'none'}); set the target only after it has been "
            "independently verified as disposable"
        ),
    ),
]


def _get(settings: Settings, path: str) -> list[dict[str, Any]]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list)
    return [dict(item) for item in body]


def _ids(items: list[dict[str, Any]]) -> list[str]:
    return [str(item["alert_id"]) for item in items]


def _restricted(items: list[dict[str, Any]], ids: set[str]) -> list[dict[str, Any]]:
    """The items whose ``alert_id`` is in ``ids``, in response order."""
    return [item for item in items if str(item["alert_id"]) in ids]


async def test_get_alerts_is_unchanged_by_a_gate_off_cycle_over_real_sql_and_http(
    db: AsyncEngine, test_settings: Settings
) -> None:
    # Seed ordinary alerts through the real repository: distinct created_at, one acknowledged and
    # one resolved through the real lifecycle method. No investment row is inserted by this test.
    repo = AlertRepository(db)
    seeded_uuids: list[uuid.UUID] = []
    for index, (alert_type, severity) in enumerate(SEEDS):
        _, row_uuid = await repo.insert_alert(
            now=SEED_BASE + timedelta(minutes=index),
            alert_type=alert_type,
            severity=severity,
            domain="BTC",
            dedup_key=f"{alert_type}:SEED{index}",
            trigger_condition=f"seeded ordinary alert {index}",
            observed_value=f"v{index}",
            reference_value=None,
            evidence_field_ids=["get_anomalies.data.BTC"],
            snapshot_id=None,
            source_tool_id="get_anomalies",
            component_status="ok",
            data_quality_state="ok",
        )
        seeded_uuids.append(row_uuid)
    assert await repo.set_status(
        seeded_uuids[1], status="acknowledged", now=SEED_BASE + timedelta(hours=1)
    )
    assert await repo.set_status(
        seeded_uuids[2], status="resolved", now=SEED_BASE + timedelta(hours=2)
    )
    seeded = [str(value) for value in seeded_uuids]
    seeded_ids = set(seeded)

    # Baseline through the real HTTP stack, real route and real repository.
    baseline = {
        "all": _get(test_settings, f"{LIST_PATH}?limit=500"),
        "active": _get(test_settings, f"{LIST_PATH}?status=active&limit=500"),
        "acknowledged": _get(test_settings, f"{LIST_PATH}?status=acknowledged&limit=500"),
        "resolved": _get(test_settings, f"{LIST_PATH}?status=resolved&limit=500"),
    }
    assert set(_ids(baseline["all"])) == seeded_ids
    # Newest first: the seeds were created in index order, so the response is the reverse.
    assert _ids(baseline["all"]) == list(reversed(seeded))
    assert _ids(baseline["acknowledged"]) == [seeded[1]]
    assert _ids(baseline["resolved"]) == [seeded[2]]
    assert set(_ids(baseline["active"])) == {seeded[0], seeded[3], seeded[4]}
    assert all(item["alert_type"] != INVESTMENT_TYPE for item in baseline["all"])

    # One real, gate-off evaluation cycle. The block must have run (so the comparison is not
    # vacuous) and must have persisted nothing.
    result = await AlertService(db, test_settings).evaluate(
        as_of=AS_OF, knowledge_time=AS_OF, now=AS_OF
    )
    assert result.investment is not None
    async with db.connect() as conn:
        stored = (
            await conn.execute(
                text("SELECT count(*) FROM usr.alert_event WHERE alert_type = :t"),
                {"t": INVESTMENT_TYPE},
            )
        ).scalar_one()
    assert stored == 0

    # After the cycle: the same endpoint, filters and limit.
    after_all = _get(test_settings, f"{LIST_PATH}?limit=500")
    assert all(item["alert_type"] != INVESTMENT_TYPE for item in after_all)
    # The ordinary alerts seeded before the cycle are unchanged, field for field and in order.
    assert _restricted(after_all, seeded_ids) == baseline["all"]
    for name in ("active", "acknowledged", "resolved"):
        after = _get(test_settings, f"{LIST_PATH}?status={name}&limit=500")
        assert all(item["alert_type"] != INVESTMENT_TYPE for item in after), name
        assert _restricted(after, seeded_ids) == baseline[name], name

    # Ordering is newest first over the whole listing, and ``limit`` is the head of that listing.
    created_at = [datetime.fromisoformat(str(item["created_at"])) for item in after_all]
    assert created_at == sorted(created_at, reverse=True)
    assert _get(test_settings, f"{LIST_PATH}?limit=2") == after_all[:2]
    assert _get(test_settings, f"{LIST_PATH}?limit=1") == after_all[:1]
