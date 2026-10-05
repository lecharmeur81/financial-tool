"""Decision read service (Phase 39): a stored ``ai.snapshot`` payload -> the UI's decision view.

Pure and read-only. It takes a payload that was already stored (and, optionally, the identity of the
row it came from), calls the Phase 38.3 ``build_decision_context`` and reshapes the result for the
Decision Center. It never builds a snapshot, never calls a provider or Claude, touches no database
and no clock, and has no randomness - the same inputs always give the same view.

What it adds on top of the context, and nothing more:

* a fixed, server-side label for each domain saying whether its evidence is asset-specific,
  market-wide, BTC-benchmarked or BTC-only (taken from the engine's scope definition);
* the **explicit reason strings the snapshot already carries** for a reading that is not available
  (``score.reason``, ``freshness.note`` and component-level ``reason``), copied verbatim from fixed
  payload paths. A cause is never inferred: when the snapshot records none, none is shown;
* the engine's template sentences, resolved from ids, so the UI shows the engine's own words.

It does not use the producer-level ``data_quality_state``, ``has_conflicts`` or
``data_quality.note`` as a completeness signal (the real snapshot reports ``ok`` while four domains
have no data). The availability shown here comes from the assessment's own reading statuses.
"""

from __future__ import annotations

from typing import Any, Final

from cfi.decision.context import (
    DecisionContext,
    UnsupportedScopeError,
    build_decision_context,
)
from cfi.decision.identity import SnapshotRef
from cfi.decision.universe import (
    DOMAIN_TOOL,
    SCOPE_DOMAINS,
    TOOL_ANOMALY,
    TOOL_DERIVATIVES,
    TOOL_REGIME,
    TOOL_RETAIL,
)

__all__ = [
    "CONTRACT_VERSION",
    "DEFAULT_ASSET",
    "SUPPORTED_ASSETS",
    "build_decision_view",
    "normalise_asset",
]

CONTRACT_VERSION: Final = "decision_view.v0"
DEFAULT_ASSET: Final = "BTC"
SUPPORTED_ASSETS: Final[tuple[str, ...]] = tuple(SCOPE_DOMAINS)

_MAX_REASONS_PER_READING: Final = 12
_MAX_REASON_CHARS: Final = 500
# Statuses that carry a ``reason`` string worth surfacing (the source says why it has no value).
_REASON_STATUSES: Final = frozenset({"unavailable", "insufficient_data"})

# Scope of each domain's evidence. A fixed mapping from the engine's own scope definition
# (``decision.universe``: perps/ETF per asset, whale BTC/ETH, regime and market structure
# BTC-benchmarked, anomaly BTC only, liquidity/macro/retail market-level) - never data-driven.
_ASSET = ("asset_specific", "Asset-specific")
_MARKET = ("market_wide", "Market-wide")
_BENCH = ("market_wide_btc_benchmarked", "Market-wide (BTC-benchmarked)")
_BTC_ONLY = ("btc_only", "BTC only")
_DOMAIN_SCOPE: Final[dict[str, tuple[str, str]]] = {
    "institutional": _ASSET,
    "whale": _ASSET,
    "derivatives": _ASSET,
    "liquidity": _MARKET,
    "macro": _MARKET,
    "retail": _MARKET,
    "market_structure": _BENCH,
    "regime": _BENCH,
    "anomaly": _BTC_ONLY,
}
_TOOL_FOR_DOMAIN: Final[dict[str, str]] = {
    **DOMAIN_TOOL,
    "derivatives": TOOL_DERIVATIVES,
    "regime": TOOL_REGIME,
    "anomaly": TOOL_ANOMALY,
    "retail": TOOL_RETAIL,
}
_ALL_DIRECTIONAL: Final = ("institutional", "whale", "liquidity", "macro", "market_structure")


def normalise_asset(asset: str | None) -> str:
    """Upper-case and validate an asset symbol; ``None`` is the default (BTC)."""
    symbol = DEFAULT_ASSET if asset is None else asset.strip().upper()
    if symbol not in SUPPORTED_ASSETS:
        raise UnsupportedScopeError(
            f"unsupported asset {asset!r}; supported: {', '.join(SUPPORTED_ASSETS)}"
        )
    return symbol


def _scope_label(domain: str) -> dict[str, str] | None:
    entry = _DOMAIN_SCOPE.get(domain)
    return None if entry is None else {"code": entry[0], "text": entry[1]}


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_REASON_CHARS else text[: _MAX_REASON_CHARS - 1] + "…"


# --------------------------------------------------------------- explicit reasons (verbatim)


def _tool_data(payload: dict[str, Any], tool_id: str) -> dict[str, Any] | None:
    results = payload.get("tool_results")
    node = results.get(tool_id) if isinstance(results, dict) else None
    data = node.get("data") if isinstance(node, dict) else None
    return data if isinstance(data, dict) else None


def _reason(kind: str, text: object, path: str) -> dict[str, str] | None:
    if not isinstance(text, str) or not text.strip():
        return None
    return {"kind": kind, "text": _clip(text), "path": path}


def _leaf_reason(node: object, path: str) -> dict[str, str] | None:
    if (
        isinstance(node, dict)
        and node.get("status") in _REASON_STATUSES
        and isinstance(node.get("reason"), str)
    ):
        return _reason("component_reason", node["reason"], f"{path}.reason")
    return None


def _component_reasons(data: dict[str, Any], base: str) -> list[dict[str, str]]:
    """Component-level ``reason`` strings: a top-level object with ``status`` unavailable /
    insufficient_data and a ``reason``, or one level inside a group of such objects (for example
    ``supply.USDT``). ``score`` is read separately."""
    out: list[dict[str, str]] = []
    for key, value in data.items():
        if key == "score" or not isinstance(value, dict):
            continue
        leaf = _leaf_reason(value, f"{base}.{key}")
        if leaf is not None:
            out.append(leaf)
            continue
        if "status" in value:
            continue
        for child_key, child in value.items():
            nested = _leaf_reason(child, f"{base}.{key}.{child_key}")
            if nested is not None:
                out.append(nested)
    return out


def _asset_entry(data: dict[str, Any], scope: str) -> tuple[int, dict[str, Any]] | None:
    assets = data.get("assets")
    if not isinstance(assets, list):
        return None
    for index, entry in enumerate(assets):
        if isinstance(entry, dict) and entry.get("asset") == scope:
            return index, entry
    return None


def _reasons_for(payload: dict[str, Any], domain: str, scope: str) -> list[dict[str, str]]:
    tool_id = _TOOL_FOR_DOMAIN.get(domain)
    data = _tool_data(payload, tool_id) if tool_id else None
    if tool_id is None or data is None:
        return []
    base = f"tool_results.{tool_id}.data"
    found: list[dict[str, str] | None] = []
    located = _asset_entry(data, scope)
    if located is not None:  # asset-specific tools: institutional / whale
        index, entry = located
        entry_base = f"{base}.assets[{index}]"
        score = entry.get("score")
        if isinstance(score, dict):
            found.append(_reason("score_reason", score.get("reason"), f"{entry_base}.score.reason"))
        freshness = entry.get("freshness")
        if isinstance(freshness, dict):
            found.append(
                _reason("freshness_note", freshness.get("note"), f"{entry_base}.freshness.note")
            )
    else:  # market-level tools
        score = data.get("score")
        if isinstance(score, dict):
            found.append(_reason("score_reason", score.get("reason"), f"{base}.score.reason"))
        found.extend(_component_reasons(data, base))
    reasons = [r for r in found if r is not None]
    return reasons[:_MAX_REASONS_PER_READING]


# ------------------------------------------------------------------------------- the view


def _evidence_state(status: str, freshness: str, flags: list[str]) -> str:
    """The reading's availability, taken from the engine's own status/freshness values."""
    if status != "ok":
        return status  # unavailable / insufficient_data / not_applicable / not_tracked
    if freshness == "stale" or "stale" in flags:
        return "stale"
    if freshness == "not_assessed":
        return "available_freshness_not_assessed"
    return "available"


def _freshness_info(ctx: DecisionContext, domain: str) -> dict[str, Any]:
    nodes = [s for s in ctx.source_freshness if s.domain == domain]
    counts: dict[str, int] = {}
    for node in nodes:
        key = node.status or "unknown"
        counts[key] = counts.get(key, 0) + 1
    first = nodes[0] if len(nodes) == 1 else None
    return {
        "status_counts": dict(sorted(counts.items())),
        "latest": None if first is None else first.latest,
        "expected_latest": None if first is None else first.expected_latest,
        "rule": None if first is None else first.rule,
        "note": None if first is None else first.note,
    }


def _text(texts: dict[str, str], template_id: str | None) -> str | None:
    return None if template_id is None else texts.get(template_id)


def _items(texts: dict[str, str], ids: list[str]) -> list[dict[str, str | None]]:
    return [{"id": i, "text": texts.get(i)} for i in ids]


def _evidence(
    texts: dict[str, str], items: list[dict[str, Any]], stance_side: str
) -> list[dict[str, Any]]:
    return [
        {
            "side": stance_side,
            "domain": item["domain"],
            "scope_label": _scope_label(item["domain"]),
            "strength": item["strength"],
            "band": item["band"],
            "text": _text(texts, item["template_id"]),
            "template_id": item["template_id"],
            "quality_flags": list(item["quality_flags"]),
            "field_ids": list(item["field_ids"]),
        }
        for item in items
    ]


def build_decision_view(
    payload: dict[str, Any],
    asset: str | None = None,
    *,
    snapshot_ref: SnapshotRef | None = None,
) -> dict[str, Any]:
    """Build the Decision Center view for ``asset`` from a stored payload.

    Raises ``UnsupportedScopeError`` for an unsupported asset and ``InvalidSnapshotError`` for a
    payload the context layer refuses (both subclasses of ``ValueError``)."""
    scope = normalise_asset(asset)
    ctx = build_decision_context(payload, scope, snapshot_ref=snapshot_ref)
    d = ctx.deterministic_dict()
    a = d["assessment"]
    dq = d["data_quality"]
    texts = {str(k): str(v) for k, v in d["template_text"]}
    expl = a["explanation"]
    stance_id = f"STANCE.{a['final_stance']}"

    domains: list[dict[str, Any]] = []
    for reading in dq["readings"]:
        domain = reading["domain"]
        state = _evidence_state(
            reading["status"], reading["freshness"], list(reading["quality_flags"])
        )
        explicit = state not in ("available", "available_freshness_not_assessed")
        domains.append(
            {
                "domain": domain,
                "component": reading["component"],
                "role": reading["role"],
                "scope_label": _scope_label(domain),
                "status": reading["status"],
                "freshness": reading["freshness"],
                "evidence_state": state,
                "quality_flags": list(reading["quality_flags"]),
                "direction": reading["direction"],
                "strength": reading["strength"],
                "band": reading["band"],
                "freshness_info": _freshness_info(ctx, domain),
                "reasons": _reasons_for(payload, domain, scope) if explicit else [],
            }
        )

    in_scope = set(SCOPE_DOMAINS[scope])
    not_in_scope = [x for x in _ALL_DIRECTIONAL if x not in in_scope]
    scope_notes: list[str] = []
    if "whale" in not_in_scope:
        scope_notes.append(
            f"Whale activity is only tracked for BTC and ETH, so it is not part of the {scope} "
            "assessment. It is not counted as bearish or neutral."
        )
    if scope != DEFAULT_ASSET:
        scope_notes.append(
            f"Liquidity, macro, market structure and regime evidence is market-wide or "
            f"BTC-benchmarked and is shared with the BTC assessment; it is not independent "
            f"analysis of {scope}."
        )

    final_stance = a["final_stance"]
    raw_stance = a["directional_stance_before_limits"]
    cap_u = [
        {
            "rule_id": c["rule_id"],
            "cap_source": c["cap_source"],
            "source_field_id": c["source_field_id"],
            "binding": c["binding"],
            "raw_stance": c["directional_stance_before_limits"],
            "applied_ceiling": c["applied_ceiling"],
            "final_stance": c["final_stance"],
            "final_posture": c["final_posture"],
            "text": _text(texts, c["template_id"]),
            "template_id": c["template_id"],
        }
        for c in a["cap_u"]
    ]
    snapshot_identity = d["identity"]
    return {
        "contract_version": CONTRACT_VERSION,
        "asset": scope,
        "stance": {
            "final": final_stance,
            "raw": raw_stance,
            "confidence": a["confidence"],
            "posture": a["posture"],
            "differs_from_raw": final_stance != raw_stance,
            "cap_u_applied": bool(cap_u),
            "headline": _text(texts, stance_id),
        },
        "why": {
            "directional": _items(texts, list(expl["directional"])),
            "limits": _items(texts, list(expl["limits"])),
            "missing_context": _items(texts, list(expl["missing_context"])),
        },
        "cap_u": cap_u,
        "observed_caps": [
            {
                "rule_id": c["rule_id"],
                "ceiling": c["ceiling"],
                "binding": c["binding"],
                "text": _text(texts, c["template_id"]),
            }
            for c in a["observed_caps"]
        ],
        "evidence": {
            "supportive": _evidence(texts, a["supportive"], "supportive"),
            "adverse": _evidence(texts, a["adverse"], "adverse"),
            "neutral": _evidence(texts, a["neutral"], "neutral"),
        },
        "conflict": {
            "directional": a["conflict"],
            "contradictions": list(a["contradictions"]),
            "conflicting_tools": list(dq["conflicting_tools"]),
        },
        "risks": [
            {
                "dimension": r["dimension"],
                "level": r["level"],
                "text": _text(texts, r["template_id"]),
            }
            for r in a["risks"]
        ],
        "max_risk": a["max_risk"],
        "coverage": {
            "available": a["coverage_available"],
            "expected": a["expected_domains"],
            "missing": list(a["missing"]),
            "missing_context": list(a["missing_context"]),
        },
        "domains": domains,
        "scope_notes": scope_notes,
        "limitations": _items(texts, list(a["limitations"])),
        "data_quality": {
            "unavailable_components": list(dq["unavailable_components"]),
            "stale_components": list(dq["stale_components"]),
            "partial_components": list(dq["partial_components"]),
            "not_assessed_components": list(dq["not_assessed_components"]),
            "unavailable_tools": list(dq["unavailable_tools"]),
            "degraded_tools": list(dq["degraded_tools"]),
            "look_ahead_violations": list(dq["look_ahead_violations"]),
            "platform_limits": list(dq["not_tracked"]),
        },
        "snapshot": {
            "row_id": snapshot_identity["row_id"],
            "uuid": snapshot_identity["uuid"],
            "row_created_at": snapshot_identity["row_created_at"],
            "as_of": snapshot_identity["as_of"],
            "knowledge_time": snapshot_identity["knowledge_time"],
            "snapshot_version": snapshot_identity["snapshot_version"],
            "producer_payload_hash": snapshot_identity["producer_payload_hash_stored"],
            "producer_hash_check": snapshot_identity["producer_hash_check"],
            "decision_input_hash": snapshot_identity["decision_input_hash"],
        },
        "methodology": {
            "methodology_version": a["methodology_version"],
            "parameter_version": a["parameter_version"],
            "template_version": a["template_version"],
            "fired_rule_ids": list(a["fired_rule_ids"]),
            "confidence_rule_ids": list(a["confidence_rule_ids"]),
            "posture_rule_id": a["posture_rule_id"],
        },
        "technical": {
            "fields": [
                {
                    "field_id": f["field_id"],
                    "display": f["display"],
                    "evidence_category": f["evidence_category"],
                    "quality_status": f["quality_status"],
                    "unit": f["unit"],
                    "source": f["source"],
                }
                for f in d["field_displays"]
                if isinstance(f.get("display"), str) and f["display"].strip()
            ],
            "fields_without_display": sum(
                1
                for f in d["field_displays"]
                if not (isinstance(f.get("display"), str) and f["display"].strip())
            ),
        },
    }
