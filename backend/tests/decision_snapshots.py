"""Real-shaped Phase 21 snapshot payloads for the Decision Context tests (Phase 38.3).

The payload is produced by the **real** ``cfi.analyst.snapshot.build_snapshot`` and
``Snapshot.payload()`` (so ``snapshot_version``, ``as_of`` / ``knowledge_time`` formatting, the
flattened ``fields`` map and the ``check_data_quality`` result are the production ones). Only the
13 tool calls are replaced by canned results, taken from the Phase 38.2 builder
(``tests/decision_builders.make_payload``) and given the production *freshness* structure
(``cfi.institutional.service.Freshness.as_dict``: ``status``, ``latest``, ``expected_latest``,
``age_seconds``, ``rule``, ``note``, with ``date`` objects exactly as the service returns them).

No database is involved, so this is a real-shaped payload, **not** a payload read back from a live
database; the PostgreSQL JSONB round trip is covered separately by an integration test.
"""

from __future__ import annotations

import copy
import json
from datetime import UTC, date, datetime
from typing import Any

import pytest

from cfi.analyst import tools as tools_module
from cfi.analyst.snapshot import Snapshot, build_snapshot
from cfi.analyst.universe import TOOLS
from cfi.core.config import Settings
from tests.decision_builders import make_payload

AS_OF = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
KNOWLEDGE_TIME = datetime(2026, 10, 5, 12, 5, tzinfo=UTC)
LATEST_DAY = date(2026, 10, 3)
STALE_DAY = date(2026, 9, 25)
_ASSET_TOOLS = ("get_institutional_flows", "get_whale_activity")
_SCORE_TOOLS = {  # domain tools whose ``score`` is the full ScoreResult payload (no "value" key)
    "get_liquidity": "liquidity_score",
    "get_macro": "macro_score",
    "get_market_structure": "market_structure_score",
}


def _real_freshness(status: str, latest: date) -> dict[str, Any]:
    return {
        "status": status,
        "latest": latest,
        "expected_latest": LATEST_DAY,
        "age_seconds": 3600 if status == "fresh" else 777600,
        "rule": "newest trading day >= latest day due",
        "note": "up to date" if status == "fresh" else "older than the latest day due",
    }


def real_tool_results(
    codes: list[str],
    *,
    scope: str = "BTC",
    quality_status: dict[str, str] | None = None,
    latest_after_knowledge: bool = False,
    **kwargs: Any,
) -> dict[str, dict[str, Any]]:
    """The 13 tool results, in the production freshness shape. ``quality_status`` injects a
    ``data_quality.status`` into a tool's data (so ``check_data_quality`` sees it, as in
    production)."""
    results: dict[str, dict[str, Any]] = copy.deepcopy(
        make_payload(codes, scope=scope, **kwargs)["tool_results"]
    )
    # The real snapshot always carries every tool; a four-domain scope has no whale reading of its
    # own, so the (unused) whale tool result of the platform's BTC reading stands in for it.
    for tool_id, fallback in make_payload(["N"] * 5, scope="BTC")["tool_results"].items():
        results.setdefault(tool_id, copy.deepcopy(fallback))
    for tool_id, score_id in _SCORE_TOOLS.items():
        data = results[tool_id].get("data")
        if data is not None:  # production shape: ``score`` carries the number under "score"
            old = data["score"]
            data["score"] = {
                "score_id": score_id,
                "version": old["version"],
                "calculated_at": "2026-10-05T11:55:00+00:00",
                "evidence_category": "Calculated Metric",
                "status": old["status"],
                "score": old["value"],
                "band": old["band"],
                "available_weight": old["available_weight"],
                "reason": None,
                "components": [],
            }
    for tool_id in _ASSET_TOOLS:
        data = results[tool_id].get("data")
        for item in (data or {}).get("assets", []):
            node = item.get("freshness")
            if isinstance(node, dict):
                latest = (
                    date(2026, 10, 9)
                    if latest_after_knowledge and item.get("asset") == scope
                    else (STALE_DAY if node.get("status") == "stale" else LATEST_DAY)
                )
                item["freshness"] = _real_freshness(node["status"], latest)
    for tool_id, status in (quality_status or {}).items():
        data = results[tool_id]["data"]
        quality = data.get("data_quality")
        if isinstance(quality, dict):
            quality["status"] = status
        else:
            data["data_quality"] = {"status": status}
    for result in results.values():
        result.setdefault("error", None)
    return results


async def build_real_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    settings: Settings,
    codes: list[str],
    *,
    scope: str = "BTC",
    question: str | None = None,
    as_of: datetime = AS_OF,
    knowledge_time: datetime = KNOWLEDGE_TIME,
    quality_status: dict[str, str] | None = None,
    latest_after_knowledge: bool = False,
    **kwargs: Any,
) -> Snapshot:
    results = real_tool_results(
        codes,
        scope=scope,
        quality_status=quality_status,
        latest_after_knowledge=latest_after_knowledge,
        **kwargs,
    )
    for tool_def in TOOLS:
        if tool_def.tool_id == "check_data_quality":
            continue

        async def fake(
            *_args: Any, _tool_id: str = tool_def.tool_id, **_kwargs: Any
        ) -> dict[str, Any]:
            return copy.deepcopy(results[_tool_id])

        monkeypatch.setattr(tools_module, tool_def.tool_id, fake)
    return await build_snapshot(
        engine=object(),
        settings=settings,
        as_of=as_of,
        knowledge_time=knowledge_time,
        question=question,
    )


def stored_form(payload: dict[str, Any]) -> dict[str, Any]:
    """The payload as the database holds it: serialised with the platform's JSON serializer
    (``json.dumps(default=str)``, ``cfi.db.engine``) and read back."""
    loaded = json.loads(json.dumps(payload, default=str))
    assert isinstance(loaded, dict)
    return loaded
