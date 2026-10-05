"""A stored-snapshot payload in the *live* data state seen in Phase 39's real-snapshot check:
institutional, liquidity, macro and market_structure all report ``insufficient_data`` with the
snapshot's own explicit reason strings, whale and derivatives have data, regime and anomaly do not.

It starts from the Phase 38.2 builder (so the engine-facing fields are the tested ones) and
replaces the four domain tool results with the real shapes: asset entries with ``score`` and
``freshness`` for institutional; a ``ScoreResult`` ``score`` plus component objects carrying
``status`` / ``reason`` for the market-level domains. The reason texts below are fixture text. The
production-shaped value is the structure, not the wording.
"""

from __future__ import annotations

from typing import Any

from tests.decision_builders import make_payload

SCORE_REASON = "Insufficient data: available components carry weight 0 of 1.00 (minimum 0.5)."
INSTITUTIONAL_NOTE = "no ETF data stored"
USDT_REASON = "no circulating-supply snapshot for USDT at or before the as_of time"
VIX_REASON = "no VIX value near as_of"
ETH_BTC_REASON = "no daily bars available for ETH and/or BTC"
BREADTH_REASON = "no tracked asset has enough history for a 50-day SMA"
GENERIC_NOTE = "Points loaded for the last 46 days."  # misleading producer text, must not surface


def _ok(tool_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"tool_id": tool_id, "status": "ok", "data": data, "error": None}


def _score() -> dict[str, Any]:
    return {
        "band": None,
        "score": None,
        "reason": SCORE_REASON,
        "status": "insufficient_data",
        "available_weight": "0",
    }


def _unavailable(reason: str) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "value": None}


def _sources(count: int) -> dict[str, Any]:
    return {
        "note": GENERIC_NOTE,
        "sources": [{"freshness": "no_data"} for _ in range(count)],
    }


def live_state_payload(*, scope: str = "BTC") -> dict[str, Any]:
    codes = ["U", "S1", "U", "U", "U"] if scope in ("BTC", "ETH") else ["U", "U", "U", "U"]
    payload = make_payload(codes, scope=scope, regime=None, volatility=None)
    payload["snapshot_version"] = "analyst_snapshot.v1"
    payload["as_of"] = "2026-10-05T23:09:52.212066+00:00"
    payload["knowledge_time"] = "2026-10-05T23:09:52.212066+00:00"
    payload["data_quality_state"] = "ok"  # the producer's flag does not see the missing domains
    payload["has_conflicts"] = False
    results = payload["tool_results"]
    results["get_institutional_flows"] = _ok(
        "get_institutional_flows",
        {
            "assets": [
                {
                    "asset": asset,
                    "score": {**_score(), "value": None},
                    "freshness": {
                        "status": "no_data",
                        "latest": None,
                        "expected_latest": "2026-10-02",
                        "age_seconds": None,
                        "rule": "newest trading day >= latest day due",
                        "note": INSTITUTIONAL_NOTE,
                    },
                }
                for asset in ("BTC", "ETH", "SOL", "XRP")
            ],
        },
    )
    results["get_liquidity"] = _ok(
        "get_liquidity",
        {
            "score": _score(),
            "supply": {"USDT": _unavailable(USDT_REASON)},
            "data_quality": _sources(3),
        },
    )
    results["get_macro"] = _ok(
        "get_macro",
        {
            "score": _score(),
            "vix": _unavailable(VIX_REASON),
            "data_quality": _sources(18),
        },
    )
    results["get_market_structure"] = _ok(
        "get_market_structure",
        {
            "score": _score(),
            "eth_btc": _unavailable(ETH_BTC_REASON),
            "market_breadth": {"status": "unavailable", "reason": BREADTH_REASON},
            "data_quality": _sources(5),
        },
    )
    return payload
