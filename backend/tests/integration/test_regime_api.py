"""Market Regime Engine API against real PostgreSQL (Phase 14).

Scope (documented, not silently narrowed — see PROGRESS.md's Phase 14 known limitations): a fully
"ok" regime classification needs all seven domains (institutional, whale, retail, liquidity,
derivatives, macro, market structure) populated at once, each of which already has its own
integration suite proving its own ingestion/scoring pipeline. Re-seeding all seven here would only
duplicate that coverage. This suite instead proves the two things that are genuinely new in this
phase and not covered elsewhere: the catalog's shape (every regime definition, weights summing to
1), and the empty-database "insufficient data" / mixed_unclear path end-to-end through the real
API. The classifier's own decision logic (which regime wins, ties, thresholds) is unit-tested
against synthetic snapshots in ``test_regime_classifier.py``; the domain-score extraction in
``cfi.regime.snapshot`` is exercised indirectly here (every field read comes back "unavailable"
with nothing loaded, proving the extraction path does not raise on empty data).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine

from cfi.api.app import create_app
from cfi.core.config import Settings
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

AS_OF = datetime(2026, 10, 5, tzinfo=UTC)


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


async def test_catalog_lists_seven_regimes_with_weights_summing_to_one(
    test_settings: Settings,
) -> None:
    status, body = get(test_settings, "/api/v1/regime/catalog")
    assert status == 200
    assert set(body["regime_ids"]) == {
        "accumulation",
        "recovery",
        "expansion",
        "euphoria",
        "distribution",
        "capitulation",
        "mixed_unclear",
    }
    assert len(body["regimes"]) == 6  # mixed_unclear is the classifier's own fallback, not defined
    assert "hysteresis_margin" in body["parameters"]  # ADR-0062, finding #4
    for regime in body["regimes"]:
        total = sum(Decimal(c["weight"]) for c in regime["conditions"])
        assert total == Decimal(1), f"{regime['regime_id']} weights sum to {total}"


async def test_current_is_mixed_unclear_when_nothing_is_loaded(
    db: AsyncEngine, test_settings: Settings
) -> None:
    """Phase 34 Finding 3: this test's premise ("nothing is loaded") requires an actually-empty
    database. It previously requested only ``test_settings``, so — unlike every other test in
    this file, which only checks catalog shape or scoring logic rather than depending on the
    database being empty — it silently inherited rows left behind by an earlier test's own
    (non-truncating) seeding fixture when run in the same session. Requesting the auto-truncating
    ``db`` fixture here restores that premise; the API behavior under test is unchanged."""
    status, body = get(
        test_settings,
        "/api/v1/regime/current",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["regime_id"] == "mixed_unclear"
    assert body["confidence"] is None
    assert body["status"] == "insufficient_data"
    assert body["contributing_metrics"] == []
    assert body["contradicting_metrics"] == []
    assert body["historical_examples"] == []
    assert body["regime_duration_days"] == 0
    assert body["regime_start_date"] is None
    assert "confidence_semantic_note" in body
    assert body["held_by_hysteresis"] is False
