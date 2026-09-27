"""Macro API against real PostgreSQL, fed through the real FRED ingestion pipeline (the fake
server, ``tests/macro_fakes.py``).

The catalog/overview shape is checked end to end here (status, evidence labelling, score
components); the underlying formulas are exercised at the unit level
(``test_macro_metrics.py``, ``test_macro_score.py``)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from cfi.api.app import create_app
from cfi.core.config import Settings
from cfi.macro.universe import (
    CPI,
    DXY_BROAD_PROXY,
    FED_BALANCE_SHEET,
    FED_FUNDS_EFFECTIVE,
    OIL_WTI,
    REVERSE_REPO,
    SP500,
    TREASURY_GENERAL_ACCOUNT,
    UST_YIELD_2Y,
    UST_YIELD_10Y,
    VIX,
)
from tests.integration.conftest import requires_services
from tests.integration.macro_support import MacroHarness

pytestmark = [pytest.mark.integration, requires_services]

# All datasets the Macro Environment Score needs, loaded with plenty of history so every
# component is available.
_SCORE_DATASETS = (
    UST_YIELD_10Y,
    UST_YIELD_2Y,
    FED_FUNDS_EFFECTIVE,
    CPI,
    VIX,
    SP500,
    DXY_BROAD_PROXY,
    FED_BALANCE_SHEET,
    TREASURY_GENERAL_ACCOUNT,
    REVERSE_REPO,
    OIL_WTI,
)


def get(settings: Settings, path: str, **params: Any) -> tuple[int, Any]:
    with TestClient(create_app(settings), raise_server_exceptions=True) as client:
        response = client.get(path, params={k: str(v) for k, v in params.items()})
    return response.status_code, response.json()


async def _load_all(macro: MacroHarness) -> None:
    for dataset in _SCORE_DATASETS:
        await macro.load(dataset.dataset_id, history_runs=2)


async def test_catalog_lists_every_dataset_and_the_score_definition(
    macro: MacroHarness, test_settings: Settings
) -> None:
    status, body = get(test_settings, "/api/v1/macro/catalog")
    assert status == 200
    dataset_ids = {d["dataset_id"] for d in body["datasets"]}
    assert VIX.dataset_id in dataset_ids
    assert CPI.dataset_id in dataset_ids
    assert body["score"]["score_id"] == "macro_environment_score"
    component_ids = {c["component_id"] for c in body["score"]["components"]}
    assert component_ids == {
        "yield_curve_slope",
        "real_policy_rate",
        "vix_level",
        "equity_trend",
        "dollar_trend",
        "net_liquidity_trend",
        "oil_trend",
    }
    assert any(item["item"] == "Gold spot price" for item in body["not_tracked"])


async def test_overview_returns_ok_score_once_every_component_has_data(
    macro: MacroHarness, test_settings: Settings
) -> None:
    await _load_all(macro)
    as_of = macro.wall.current
    status, body = get(
        test_settings,
        "/api/v1/macro/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    assert body["score"]["status"] == "ok"
    assert body["score"]["score"] is not None
    assert body["score"]["available_weight"] == "1.00"
    for section in ("yield_curve", "vix", "us_net_liquidity"):
        assert body[section]["status"] == "ok"
    assert "not a crypto price prediction" in body["score"]["semantic_note"]
    assert "not a true global aggregate" in body["us_net_liquidity"]["calculation"]


async def test_overview_is_insufficient_when_nothing_is_loaded(
    macro: MacroHarness, test_settings: Settings
) -> None:
    as_of = macro.wall.current
    status, body = get(
        test_settings,
        "/api/v1/macro/overview",
        as_of=as_of.isoformat(),
        knowledge_time=as_of.isoformat(),
    )
    assert status == 200
    assert body["score"]["status"] == "insufficient_data"
    assert body["score"]["score"] is None


async def test_history_returns_points_for_a_tracked_dataset(
    macro: MacroHarness, test_settings: Settings
) -> None:
    await macro.load(VIX.dataset_id, history_runs=1)
    as_of = macro.wall.current
    status, body = get(
        test_settings,
        "/api/v1/macro/history",
        dataset_id=VIX.dataset_id,
        days=30,
        as_of=as_of.isoformat(),
    )
    assert status == 200
    assert body["dataset_id"] == VIX.dataset_id
    assert len(body["points"]) > 0


async def test_history_rejects_unknown_dataset(
    macro: MacroHarness, test_settings: Settings
) -> None:
    as_of = macro.wall.current
    status, _body = get(
        test_settings,
        "/api/v1/macro/history",
        dataset_id="macro.not_real",
        days=30,
        as_of=as_of.isoformat(),
    )
    assert status == 404
