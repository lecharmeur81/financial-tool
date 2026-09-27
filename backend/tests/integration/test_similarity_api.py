"""Historical Similarity Engine API against real PostgreSQL (Phase 15).

Scope (documented, not silently narrowed — mirrors ``test_regime_api.py``'s own Phase 14 scope
decision): a fully "ok" similarity search needs the same seven domains populated across many
historical dates, each of which already has its own integration suite proving its own
ingestion/scoring pipeline, and the scoring/selection logic itself is unit-tested against synthetic
snapshots in ``test_similarity_scorer.py`` and ``test_similarity_search.py``. This suite proves the
two things genuinely new here and not covered elsewhere: the catalog's shape (9 features, weights
summing to 1), and the empty-database "insufficient data" path end-to-end through the real API.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from tests.integration.conftest import requires_services

pytestmark = [pytest.mark.integration, requires_services]

AS_OF = datetime(2026, 10, 5, tzinfo=UTC)


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


async def test_catalog_lists_nine_features_with_weights_summing_to_one(
    test_settings: Settings,
) -> None:
    status, body = get(test_settings, "/api/v1/similarity/catalog")
    assert status == 200
    assert len(body["features"]) == 9
    total = sum(Decimal(f["weight"]) for f in body["features"])
    assert total == Decimal("1.00")
    assert body["benchmark_asset"] == "BTC"


async def test_current_is_insufficient_data_when_nothing_is_loaded(
    test_settings: Settings,
) -> None:
    status, body = get(
        test_settings,
        "/api/v1/similarity/current",
        as_of=AS_OF.isoformat(),
        knowledge_time=AS_OF.isoformat(),
    )
    assert status == 200
    assert body["status"] == "insufficient_data"
    assert body["analogues"] == []
    assert body["distribution"] == []
    assert "evidence_note" in body
