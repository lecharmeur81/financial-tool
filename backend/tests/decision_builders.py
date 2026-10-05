"""Synthetic snapshot-payload builders for the L4.5 decision tests.

The band strings below are deliberately written out literally (copied from each domain's own score
parameters) rather than imported from ``cfi.decision``, so the tests cross-check the engine's
vocabulary instead of echoing it. A payload has the exact shape of ``Snapshot.payload()``:
``tool_results[tool_id] = {"tool_id", "status", "data"}``.

Reading codes (one per directional domain, in the scope's domain order):
``S2`` strong supportive, ``S1`` supportive, ``N`` neutral, ``A1`` adverse, ``A2`` strong adverse,
``U`` unavailable; a trailing ``~`` marks a stale reading and ``*`` a partial one.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

BANDS: dict[str, dict[str, str]] = {
    "institutional": {
        "S2": "strong net inflow",
        "S1": "net inflow",
        "N": "balanced",
        "A1": "net outflow",
        "A2": "strong net outflow",
    },
    "whale": {
        "S2": "strong accumulation",
        "S1": "accumulation",
        "N": "neutral",
        "A1": "distribution",
        "A2": "strong distribution",
    },
    "liquidity": {
        "S2": "strong liquidity expansion",
        "S1": "liquidity expansion",
        "N": "stable",
        "A1": "liquidity contraction",
        "A2": "strong liquidity contraction",
    },
    "macro": {
        "S2": "broadly accommodative macro backdrop",
        "S1": "improving macro backdrop",
        "N": "neutral / mixed macro backdrop",
        "A1": "tightening macro backdrop",
        "A2": "broadly restrictive macro backdrop",
    },
    "market_structure": {
        "S2": "broadly constructive technical structure",
        "S1": "improving technical structure",
        "N": "neutral / mixed technical structure",
        "A1": "deteriorating technical structure",
        "A2": "broadly weak technical structure",
    },
}
TOOLS = {
    "institutional": "get_institutional_flows",
    "whale": "get_whale_activity",
    "liquidity": "get_liquidity",
    "macro": "get_macro",
    "market_structure": "get_market_structure",
}
DOMAINS_5 = ("institutional", "whale", "liquidity", "macro", "market_structure")
DOMAINS_4 = ("institutional", "liquidity", "macro", "market_structure")
DEFAULT_ACTIVITY = "typical retail-proxy activity"
DEFAULT_SPECULATION = "balanced"
ELEVATED_ACTIVITY = "elevated retail-proxy activity"
STRONG_LONG = "strong long-biased speculative skew"


def unavailable_tool(tool_id: str) -> dict[str, Any]:
    return {
        "tool_id": tool_id,
        "status": "unavailable",
        "data": None,
        "error": {"error_code": "unavailable", "detail": "test"},
    }


def _ok(tool_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"tool_id": tool_id, "status": "ok", "data": data}


def parse_code(code: str) -> tuple[str, bool, bool]:
    """``"S2~"`` -> ("S2", stale=True, partial=False)."""
    stale = "~" in code
    partial = "*" in code
    return code.replace("~", "").replace("*", ""), stale, partial


def domains_for(scope: str) -> tuple[str, ...]:
    return DOMAINS_4 if scope in ("SOL", "XRP") else DOMAINS_5


def _decoy(scope: str) -> str:
    return "XRP" if scope == "SOL" else "SOL"


def _directional_tool(domain: str, scope: str, code: str) -> dict[str, Any]:
    base, stale, partial = parse_code(code)
    tool_id = TOOLS[domain]
    if base == "U":
        return unavailable_tool(tool_id)
    score = {
        "status": "ok",
        "value": "0",
        "band": BANDS[domain][base],
        "available_weight": "0.7" if partial else "1",
    }
    if domain in ("institutional", "whale"):
        decoy_score = {
            "status": "ok",
            "value": "0",
            "band": BANDS[domain]["A2"],
            "available_weight": "1",
        }
        return _ok(
            tool_id,
            {
                "assets": [
                    {
                        "asset": _decoy(scope),
                        "score": decoy_score,
                        "freshness": {"status": "fresh"},
                    },
                    {
                        "asset": scope,
                        "score": score,
                        "freshness": {"status": "stale" if stale else "fresh"},
                    },
                ]
            },
        )
    return _ok(
        tool_id,
        {
            "score": {**score, "version": f"{domain}_score_v1"},
            "data_quality": {
                "sources": [
                    {
                        "enabled": True,
                        "freshness": "stale" if stale else "fresh",
                        "flagged_points": 0,
                        "missing_points": 0,
                    }
                ]
            },
        },
    )


def make_payload(
    codes: Sequence[str],
    *,
    scope: str = "BTC",
    regime: str | None = "expansion",
    derivatives: str | None = "low stress",
    derivatives_freshness: str | None = None,
    derivatives_conditions: Iterable[str] = (),
    volatility: str | None = "normal",
    extreme_other: bool = False,
    activity: str | None = DEFAULT_ACTIVITY,
    speculation: str | None = DEFAULT_SPECULATION,
    has_conflicts: bool = False,
    missing_tools: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a payload. ``None`` for a context argument makes that tool unavailable (a missing cap
    source); ``extreme_other`` adds an extreme-band anomaly entry for a non-volatility metric."""
    domains = domains_for(scope)
    if len(codes) != len(domains):
        raise ValueError(f"scope {scope} needs {len(domains)} codes, got {len(codes)}")
    results: dict[str, Any] = {}
    for domain, code in zip(domains, codes, strict=True):
        results[TOOLS[domain]] = _directional_tool(domain, scope, code)
    results["get_market_regime"] = (
        unavailable_tool("get_market_regime")
        if regime is None
        else _ok("get_market_regime", {"status": "ok", "regime_id": regime})
    )
    if derivatives is None:
        results["get_derivatives"] = unavailable_tool("get_derivatives")
    else:
        item: dict[str, Any] = {
            "asset": scope,
            "band": derivatives,
            "score_status": "ok",
            "active_conditions": list(derivatives_conditions),
        }
        if derivatives_freshness is not None:
            item["freshness"] = {"status": derivatives_freshness}
        results["get_derivatives"] = _ok("get_derivatives", {"assets": [item]})
    if volatility is None:
        results["get_anomalies"] = unavailable_tool("get_anomalies")
    else:
        entries = [
            {"metric_id": "volatility", "asset": "BTC", "band": volatility, "status": "ok"},
            {"metric_id": "funding", "asset": "BTC", "band": "normal", "status": "ok"},
        ]
        if extreme_other:
            entries.append(
                {
                    "metric_id": "open_interest",
                    "asset": "BTC",
                    "band": "extreme_high",
                    "status": "ok",
                }
            )
        results["get_anomalies"] = _ok("get_anomalies", {"asset": "BTC", "anomalies": entries})
    if activity is None and speculation is None:
        results["get_retail_activity"] = unavailable_tool("get_retail_activity")
    else:
        results["get_retail_activity"] = _ok(
            "get_retail_activity",
            {
                "activity_score": {
                    "status": "ok" if activity else "insufficient_data",
                    "band": activity,
                },
                "speculation_score": {
                    "status": "ok" if speculation else "insufficient_data",
                    "band": speculation,
                },
                "data_quality": {"sources": []},
            },
        )
    results["find_historical_similar_periods"] = _ok(
        "find_historical_similar_periods", {"status": "ok"}
    )
    results["calculate_divergence"] = _ok(
        "calculate_divergence", {"comparisons": [{"comparison_id": "x", "is_divergent": False}]}
    )
    results["get_capital_rotation"] = _ok(
        "get_capital_rotation",
        {"pairs": [{"inferred_capital_rotation": {"status": "no_rotation_signal"}}]},
    )
    results["get_market_data"] = _ok("get_market_data", {"assets": [{"asset": scope}]})
    for tool_id in missing_tools:
        results[tool_id] = unavailable_tool(tool_id)
    return {
        "snapshot_version": "test",
        "as_of": "2026-10-05T00:00:00+00:00",
        "knowledge_time": "2026-10-05T00:00:00+00:00",
        "question": None,
        "tools_called": sorted(results),
        "not_tracked": ["mid-cap assets"],
        "data_quality_state": "ok",
        "has_conflicts": has_conflicts,
        "fields": {},
        "tool_results": results,
    }
