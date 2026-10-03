"""`cfi.alerts.rules`: trigger conditions, non-trigger conditions, threshold boundaries, missing
data, stale data, and no-trading-directive text — all pure, database-free (Phase 23 spec
"Testing")."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from cfi.alerts.rules import (
    evaluate_all,
    evaluate_anomaly,
    evaluate_capital_rotation,
    evaluate_derivatives,
    evaluate_divergence,
    evaluate_institutional_flow,
    evaluate_liquidity,
    evaluate_regime_change,
    evaluate_retail_activity,
    evaluate_whale_activity,
)
from cfi.alerts.universe import BANNED_PATTERNS
from cfi.analyst.snapshot import Snapshot

AS_OF = datetime(2026, 10, 3, tzinfo=UTC)


def _snapshot(raw: dict[str, Any]) -> Snapshot:
    return Snapshot(
        snapshot_id="deadbeef",
        snapshot_version="analyst_snapshot.v1",
        created_at=AS_OF,
        as_of=AS_OF,
        knowledge_time=AS_OF,
        question=None,
        tools_called=list(raw),
        fields=[],
        field_index={},
        raw=raw,
        data_quality_state="ok",
        has_conflicts=False,
    )


def _ok(tool_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {tool_id: {"tool_id": tool_id, "status": "ok", "data": data, "error": None}}


# ----------------------------------------------------------------- institutional_flow / whale


def test_institutional_flow_triggers_on_a_usable_score_band() -> None:
    snap = _snapshot(
        _ok(
            "get_institutional_flows",
            {
                "assets": [
                    {
                        "asset": "BTC",
                        "score": {"status": "ok", "value": "12.5", "band": "accumulation"},
                    }
                ]
            },
        )
    )
    out = evaluate_institutional_flow(snap)
    assert len(out) == 1
    assert out[0].domain == "BTC"
    assert out[0].observed_value == "accumulation"
    assert out[0].dedup_key == "institutional_flow:BTC"


def test_institutional_flow_non_trigger_when_score_is_insufficient() -> None:
    """Missing/insufficient data -> no candidate at all ("If required data is unavailable, do
    not generate the alert")."""
    snap = _snapshot(
        _ok(
            "get_institutional_flows",
            {"assets": [{"asset": "BTC", "score": {"status": "insufficient_data", "band": None}}]},
        )
    )
    assert evaluate_institutional_flow(snap) == []


def test_whale_activity_mirrors_institutional_shape() -> None:
    snap = _snapshot(
        _ok(
            "get_whale_activity",
            {
                "assets": [
                    {
                        "asset": "ETH",
                        "score": {"status": "ok", "value": "3.0", "band": "distribution"},
                    }
                ]
            },
        )
    )
    out = evaluate_whale_activity(snap)
    assert out[0].alert_type == "whale_activity"
    assert out[0].domain == "ETH"


# ----------------------------------------------------------------- retail (two independent scores)


def test_retail_activity_emits_one_candidate_per_score() -> None:
    snap = _snapshot(
        _ok(
            "get_retail_activity",
            {
                "activity_score": {"status": "ok", "score": "40", "band": "moderate"},
                "speculation_score": {"status": "ok", "score": "80", "band": "elevated"},
            },
        )
    )
    out = evaluate_retail_activity(snap)
    assert {c.domain for c in out} == {"activity_score", "speculation_score"}


def test_retail_activity_skips_the_unusable_score_only() -> None:
    snap = _snapshot(
        _ok(
            "get_retail_activity",
            {
                "activity_score": {"status": "ok", "score": "40", "band": "moderate"},
                "speculation_score": {"status": "insufficient_data", "band": None},
            },
        )
    )
    out = evaluate_retail_activity(snap)
    assert len(out) == 1
    assert out[0].domain == "activity_score"


# ----------------------------------------------------------------- derivatives (flat per-asset
# band)


def test_derivatives_reads_the_flat_band_field() -> None:
    snap = _snapshot(
        _ok(
            "get_derivatives",
            {"assets": [{"asset": "BTC", "band": "elevated stress", "score_status": "ok"}]},
        )
    )
    out = evaluate_derivatives(snap)
    assert out[0].observed_value == "elevated stress"
    assert out[0].evidence_field_ids == ("get_derivatives.assets[0].band",)


# ----------------------------------------------------------------- liquidity/macro/market_structure
# (global, not asset-specific)


def test_liquidity_is_global_not_per_asset() -> None:
    snap = _snapshot(
        _ok("get_liquidity", {"score": {"status": "ok", "score": "55", "band": "neutral"}})
    )
    out = evaluate_liquidity(snap)
    assert out[0].domain == "GLOBAL"
    assert out[0].dedup_key == "liquidity:GLOBAL"


# ----------------------------------------------------------------- missing/stale data (whole tool)


def test_missing_tool_result_produces_no_candidates() -> None:
    snap = _snapshot({})
    assert evaluate_institutional_flow(snap) == []
    assert evaluate_liquidity(snap) == []


def test_tool_level_failure_produces_no_candidates() -> None:
    """A tool that itself reported `status != "ok"` (e.g. an `unavailable` CFIError) is the
    platform's own first-class missing state — never treated as a usable zero/default."""
    snap = _snapshot(
        {
            "get_liquidity": {
                "tool_id": "get_liquidity",
                "status": "unavailable",
                "data": None,
                "error": "x",
            }
        }
    )
    assert evaluate_liquidity(snap) == []


# ----------------------------------------------------------------- flagged-state types: divergence


def test_divergence_triggers_only_when_is_divergent_is_true() -> None:
    snap = _snapshot(
        _ok(
            "calculate_divergence",
            {
                "comparisons": [
                    {
                        "comparison_id": "c1",
                        "title": "Institutional vs Retail",
                        "is_divergent": True,
                        "observed_quadrant": "Q1",
                    },
                    {
                        "comparison_id": "c2",
                        "title": "Whale vs Price",
                        "is_divergent": False,
                        "observed_quadrant": "Q2",
                    },
                    {
                        "comparison_id": "c3",
                        "title": "Unavailable pair",
                        "is_divergent": None,
                        "observed_quadrant": None,
                    },
                ]
            },
        )
    )
    out = evaluate_divergence(snap)
    assert len(out) == 1
    assert out[0].dedup_key == "divergence:c1"


# ----------------------------------------------------------------- flagged-state types: anomaly
# (threshold boundary across the platform's own closed Band vocabulary)


def test_anomaly_boundary_normal_band_does_not_trigger() -> None:
    snap = _snapshot(
        _ok(
            "get_anomalies",
            {
                "anomalies": [
                    {"metric_id": "m1", "label": "Funding", "band": "normal", "status": "ok"}
                ]
            },
        )
    )
    assert evaluate_anomaly(snap) == []


def test_anomaly_boundary_notable_band_triggers_as_notable_severity() -> None:
    snap = _snapshot(
        _ok(
            "get_anomalies",
            {
                "anomalies": [
                    {"metric_id": "m1", "label": "Funding", "band": "notable_high", "status": "ok"}
                ]
            },
        )
    )
    out = evaluate_anomaly(snap)
    assert out[0].severity == "notable"


def test_anomaly_boundary_extreme_band_triggers_as_critical_severity() -> None:
    snap = _snapshot(
        _ok(
            "get_anomalies",
            {
                "anomalies": [
                    {"metric_id": "m1", "label": "Funding", "band": "extreme_high", "status": "ok"}
                ]
            },
        )
    )
    out = evaluate_anomaly(snap)
    assert out[0].severity == "critical"


def test_anomaly_unavailable_band_does_not_trigger() -> None:
    snap = _snapshot(
        _ok(
            "get_anomalies",
            {
                "anomalies": [
                    {
                        "metric_id": "m1",
                        "label": "Funding",
                        "band": "unavailable",
                        "status": "insufficient_data",
                    }
                ]
            },
        )
    )
    assert evaluate_anomaly(snap) == []


# ----------------------------------------------------------------- flagged-state types: rotation


def test_capital_rotation_triggers_only_on_possible_rotation() -> None:
    snap = _snapshot(
        _ok(
            "get_capital_rotation",
            {
                "pairs": [
                    {
                        "from_node": {"node_id": "btc"},
                        "to_node": {"node_id": "eth"},
                        "inferred_capital_rotation": {
                            "status": "possible_rotation",
                            "hypothesis": "BTC decreased while ETH increased.",
                        },
                    },
                    {
                        "from_node": {"node_id": "eth"},
                        "to_node": {"node_id": "sol"},
                        "inferred_capital_rotation": {
                            "status": "no_rotation_signal",
                            "hypothesis": None,
                        },
                    },
                ]
            },
        )
    )
    out = evaluate_capital_rotation(snap)
    assert len(out) == 1
    assert out[0].dedup_key == "capital_rotation:btc->eth"


# ----------------------------------------------------------------- regime_change (confidence
# threshold boundary)


def test_regime_change_boundary_below_high_confidence_is_notable() -> None:
    snap = _snapshot(
        _ok("get_market_regime", {"status": "ok", "regime_id": "risk_on", "confidence": "0.69"})
    )
    out = evaluate_regime_change(snap)
    assert out[0].severity == "notable"


def test_regime_change_boundary_at_high_confidence_is_elevated() -> None:
    snap = _snapshot(
        _ok("get_market_regime", {"status": "ok", "regime_id": "risk_on", "confidence": "0.70"})
    )
    out = evaluate_regime_change(snap)
    assert out[0].severity == "elevated"


def test_regime_change_non_trigger_when_insufficient_data() -> None:
    snap = _snapshot(
        _ok(
            "get_market_regime",
            {"status": "insufficient_data", "regime_id": None, "confidence": None},
        )
    )
    assert evaluate_regime_change(snap) == []


# ----------------------------------------------------------------- no trading directives


def test_no_candidate_text_anywhere_contains_banned_directive_language() -> None:
    """Severity describes significance, never a trading recommendation (Phase 23 spec
    "Severity") — enforced the same structural way Phases 21/22 already enforce it on AI text,
    reused here over every hand-written template string this engine can produce."""
    snap = _snapshot(
        {
            **_ok(
                "get_institutional_flows",
                {
                    "assets": [
                        {
                            "asset": "BTC",
                            "score": {"status": "ok", "value": "1", "band": "accumulation"},
                        }
                    ]
                },
            ),
            **_ok(
                "get_capital_rotation",
                {
                    "pairs": [
                        {
                            "from_node": {"node_id": "btc"},
                            "to_node": {"node_id": "eth"},
                            "inferred_capital_rotation": {
                                "status": "possible_rotation",
                                "hypothesis": (
                                    "BTC decreased while ETH increased over the same window — "
                                    "consistent with (but not proof of) capital rotating from "
                                    "the former into the latter."
                                ),
                            },
                        }
                    ]
                },
            ),
            **_ok(
                "get_anomalies",
                {
                    "anomalies": [
                        {
                            "metric_id": "m1",
                            "label": "Funding",
                            "band": "extreme_high",
                            "status": "ok",
                        }
                    ]
                },
            ),
        }
    )
    candidates = evaluate_all(snap)
    assert candidates  # sanity: the fixture actually produced something to check
    for candidate in candidates:
        for text in (candidate.trigger_condition, candidate.observed_value, candidate.severity):
            for name, pattern in BANNED_PATTERNS.items():
                assert not pattern.search(text), (
                    f"{name} matched {text!r} in {candidate.alert_type}"
                )
