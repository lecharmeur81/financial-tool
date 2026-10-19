"""The deterministic alert rule engine (Phase 23 spec "Alert Engine"/"Grounding").

Every evaluator below reads directly from ``cfi.analyst.snapshot.Snapshot.raw`` — the exact,
already-computed, already-tested domain-service output the same immutable snapshot stores
verbatim in ``ai.snapshot.payload`` (ADR-0041: reproducible after the fact). Nothing here computes
a new metric, fits a new threshold to data, or calls a domain service directly (R13: reuse, do not
invent a parallel data path) — these functions only read already-published fields and decide
whether their already-defined trigger condition is satisfied.

No evaluator ever invents a value: if the tool itself did not run (``status != "ok"``), if the
specific field is missing, or if the specific component's own ``status`` says
``insufficient_data``/``unavailable``/``not_applicable``, the evaluator silently skips that one
item and produces no candidate for it ("If required data is unavailable, do not generate the
alert"). No evaluator is async and none calls the database — rules are pure functions of one
``Snapshot``, which is what makes them unit-testable without a reachable database.

Two trigger styles, deliberately not unified into one mechanism (see ``cfi.alerts.universe``'s
module docstring and DECISIONS.md ADR-0071 for why):

1. The 7 score-bearing domains (institutional, whale, retail x2, derivatives, liquidity, macro,
   market_structure) plus regime_change always report the CURRENT categorical state (a band label
   or regime id) for every asset/domain with usable data. Whether that state is actually a *change*
   worth alerting on on is decided afterwards, by ``cfi.alerts.lifecycle.decide`` against the last
   stored alert for the same dedup key — never here.
2. divergence / anomaly / capital_rotation only produce a candidate when the domain's own
   already-computed flag is itself positive (``is_divergent``, a non-``normal``/``unavailable``
   anomaly ``Band``, or ``inferred_capital_rotation.status == "possible_rotation"``). These three
   are flagged-state detections by definition (CLAUDE.md A2: a divergence, an anomaly and an
   inferred rotation hypothesis are themselves L3/L6 findings, not a raw value whose *change* must
   be separately detected) — a non-divergent pair, a normal-band metric, or a "no_rotation_signal"
   pair is the explicit non-trigger case for each.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.alerts.universe import ALERT_TYPE_TOOL_IDS, HIGH_CONFIDENCE_REGIME_THRESHOLD
from cfi.analyst.snapshot import Snapshot

# Anomaly bands that represent a flagged (non-normal, available) reading — the platform's own
# closed vocabulary (``cfi.anomaly.universe.Band``), not invented here.
_FLAGGED_ANOMALY_BANDS = frozenset({"extreme_high", "notable_high", "notable_low", "extreme_low"})
_EXTREME_ANOMALY_BANDS = frozenset({"extreme_high", "extreme_low"})

# Component-level statuses that mean "no usable reading" across the domain services (R3's
# first-class missing/insufficient state, reused directly rather than reinventing a parallel one).
_UNUSABLE_STATUSES = frozenset({"insufficient_data", "unavailable", "not_applicable"})


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    alert_type: str
    severity: str
    domain: str  # the asset symbol, or "GLOBAL" for a platform-wide (non-asset-specific) domain
    trigger_condition: str
    observed_value: str
    reference_value: str | None
    evidence_field_ids: tuple[str, ...]
    source_tool_id: str
    component_status: str
    dedup_key: str


def _field_id(tool_id: str, *path: str) -> str:
    return tool_id + "".join(path)


def _tool_data(snapshot: Snapshot, tool_id: str) -> dict[str, Any] | None:
    result = snapshot.raw.get(tool_id)
    if result is None or result.get("status") != "ok" or result.get("data") is None:
        return None
    data: dict[str, Any] = result["data"]
    return data


def _per_asset_score_band(
    snapshot: Snapshot, *, alert_type: str, tool_id: str
) -> list[AlertCandidate]:
    """institutional_flow / whale_activity: ``assets[i].score`` (status/value/band/reason)."""
    data = _tool_data(snapshot, tool_id)
    if data is None:
        return []
    out: list[AlertCandidate] = []
    for i, item in enumerate(data.get("assets") or []):
        score = item.get("score") or {}
        status = score.get("status")
        if status in _UNUSABLE_STATUSES or status is None:
            continue
        band = score.get("band")
        asset = item.get("asset")
        if band is None or asset is None:
            continue
        out.append(
            AlertCandidate(
                alert_type=alert_type,
                severity="notable",
                domain=str(asset),
                trigger_condition=f"{alert_type} score band for {asset}",
                observed_value=str(band),
                reference_value=None,
                evidence_field_ids=(_field_id(tool_id, f".assets[{i}].score"),),
                source_tool_id=tool_id,
                component_status=str(status),
                dedup_key=f"{alert_type}:{asset}",
            )
        )
    return out


def evaluate_institutional_flow(snapshot: Snapshot) -> list[AlertCandidate]:
    return _per_asset_score_band(
        snapshot,
        alert_type="institutional_flow",
        tool_id=ALERT_TYPE_TOOL_IDS["institutional_flow"],
    )


def evaluate_whale_activity(snapshot: Snapshot) -> list[AlertCandidate]:
    return _per_asset_score_band(
        snapshot, alert_type="whale_activity", tool_id=ALERT_TYPE_TOOL_IDS["whale_activity"]
    )


def evaluate_retail_activity(snapshot: Snapshot) -> list[AlertCandidate]:
    """retail_activity: two independent scores, ``activity_score`` and ``speculation_score``
    (``cfi.retail.service`` exposes these as two top-level keys, not one ``score`` key like the
    other six score-bearing domains — see the Phase 23 investigation notes)."""
    tool_id = ALERT_TYPE_TOOL_IDS["retail_activity"]
    data = _tool_data(snapshot, tool_id)
    if data is None:
        return []
    out: list[AlertCandidate] = []
    for score_key in ("activity_score", "speculation_score"):
        score = data.get(score_key) or {}
        status = score.get("status")
        band = score.get("band")
        if status in _UNUSABLE_STATUSES or status is None or band is None:
            continue
        out.append(
            AlertCandidate(
                alert_type="retail_activity",
                severity="notable",
                domain=score_key,
                trigger_condition=f"Retail {score_key.replace('_', ' ')} band",
                observed_value=str(band),
                reference_value=None,
                evidence_field_ids=(_field_id(tool_id, f".{score_key}"),),
                source_tool_id=tool_id,
                component_status=str(status),
                dedup_key=f"retail_activity:{score_key}",
            )
        )
    return out


def evaluate_derivatives(snapshot: Snapshot) -> list[AlertCandidate]:
    """derivatives: ``assets[i].band`` is already flattened (not nested under a ``score`` key) —
    see the Phase 23 investigation notes."""
    tool_id = ALERT_TYPE_TOOL_IDS["derivatives"]
    data = _tool_data(snapshot, tool_id)
    if data is None:
        return []
    out: list[AlertCandidate] = []
    for i, item in enumerate(data.get("assets") or []):
        status = item.get("score_status")
        band = item.get("band")
        asset = item.get("asset")
        if status in _UNUSABLE_STATUSES or status is None or band is None or asset is None:
            continue
        out.append(
            AlertCandidate(
                alert_type="derivatives",
                severity="notable",
                domain=str(asset),
                trigger_condition=f"Derivatives Health Score band for {asset}",
                observed_value=str(band),
                reference_value=None,
                evidence_field_ids=(_field_id(tool_id, f".assets[{i}].band"),),
                source_tool_id=tool_id,
                component_status=str(status),
                dedup_key=f"derivatives:{asset}",
            )
        )
    return out


def _global_score_band(
    snapshot: Snapshot, *, alert_type: str, tool_id: str
) -> list[AlertCandidate]:
    """liquidity / macro / market_structure: one platform-wide ``score`` dict with its own
    ``band`` key (these domains are not asset-specific, unlike institutional/whale/derivatives)."""
    data = _tool_data(snapshot, tool_id)
    if data is None:
        return []
    score = data.get("score") or {}
    status = score.get("status")
    band = score.get("band")
    if status in _UNUSABLE_STATUSES or status is None or band is None:
        return []
    return [
        AlertCandidate(
            alert_type=alert_type,
            severity="notable",
            domain="GLOBAL",
            trigger_condition=f"{alert_type} score band",
            observed_value=str(band),
            reference_value=None,
            evidence_field_ids=(_field_id(tool_id, ".score.band"),),
            source_tool_id=tool_id,
            component_status=str(status),
            dedup_key=f"{alert_type}:GLOBAL",
        )
    ]


def evaluate_liquidity(snapshot: Snapshot) -> list[AlertCandidate]:
    return _global_score_band(
        snapshot, alert_type="liquidity", tool_id=ALERT_TYPE_TOOL_IDS["liquidity"]
    )


def evaluate_macro(snapshot: Snapshot) -> list[AlertCandidate]:
    return _global_score_band(snapshot, alert_type="macro", tool_id=ALERT_TYPE_TOOL_IDS["macro"])


def evaluate_market_structure(snapshot: Snapshot) -> list[AlertCandidate]:
    return _global_score_band(
        snapshot, alert_type="market_structure", tool_id=ALERT_TYPE_TOOL_IDS["market_structure"]
    )


def evaluate_divergence(snapshot: Snapshot) -> list[AlertCandidate]:
    """divergence: a flagged-state detection — only ``is_divergent is True`` pairs produce a
    candidate (non-divergent and ``None``/unavailable pairs are the explicit non-trigger case)."""
    tool_id = ALERT_TYPE_TOOL_IDS["divergence"]
    data = _tool_data(snapshot, tool_id)
    if data is None:
        return []
    out: list[AlertCandidate] = []
    for i, c in enumerate(data.get("comparisons") or []):
        if c.get("is_divergent") is not True:
            continue
        comparison_id = c.get("comparison_id")
        if comparison_id is None:
            continue
        title = c.get("title", comparison_id)
        out.append(
            AlertCandidate(
                alert_type="divergence",
                severity="notable",
                domain=str(c.get("asset") or comparison_id),
                trigger_condition=f"{title}: observed quadrant is divergent",
                observed_value=str(c.get("observed_quadrant")),
                reference_value=None,
                evidence_field_ids=(_field_id(tool_id, f".comparisons[{i}].is_divergent"),),
                source_tool_id=tool_id,
                component_status="ok",
                dedup_key=f"divergence:{comparison_id}",
            )
        )
    return out


def evaluate_anomaly(snapshot: Snapshot) -> list[AlertCandidate]:
    """anomaly: a flagged-state detection — only a non-``normal``, non-``unavailable`` ``Band``
    produces a candidate; severity is "critical" for the extreme bands, "notable" for notable
    bands (the platform's own closed, disclosed band vocabulary, not invented here)."""
    tool_id = ALERT_TYPE_TOOL_IDS["anomaly"]
    data = _tool_data(snapshot, tool_id)
    if data is None:
        return []
    out: list[AlertCandidate] = []
    for i, a in enumerate(data.get("anomalies") or []):
        band = a.get("band")
        if band not in _FLAGGED_ANOMALY_BANDS:
            continue
        metric_id = a.get("metric_id")
        if metric_id is None:
            continue
        out.append(
            AlertCandidate(
                alert_type="anomaly",
                severity="critical" if band in _EXTREME_ANOMALY_BANDS else "notable",
                domain=str(a.get("asset") or metric_id),
                trigger_condition=f"{a.get('label', metric_id)} is in an anomalous band",
                observed_value=str(band),
                reference_value="normal",
                evidence_field_ids=(_field_id(tool_id, f".anomalies[{i}].band"),),
                source_tool_id=tool_id,
                component_status=str(a.get("status") or "ok"),
                dedup_key=f"anomaly:{metric_id}",
            )
        )
    return out


def evaluate_capital_rotation(snapshot: Snapshot) -> list[AlertCandidate]:
    """capital_rotation: a flagged-state detection — only pairs whose edge status is
    ``possible_rotation`` produce a candidate (an inferred hypothesis, never confirmed capital
    movement, CLAUDE.md A2/R1 — hence severity stays at "notable", never elevated)."""
    tool_id = ALERT_TYPE_TOOL_IDS["capital_rotation"]
    data = _tool_data(snapshot, tool_id)
    if data is None:
        return []
    out: list[AlertCandidate] = []
    for i, p in enumerate(data.get("pairs") or []):
        rotation = p.get("inferred_capital_rotation") or {}
        if rotation.get("status") != "possible_rotation":
            continue
        from_node = (p.get("from_node") or {}).get("node_id")
        to_node = (p.get("to_node") or {}).get("node_id")
        if from_node is None or to_node is None:
            continue
        out.append(
            AlertCandidate(
                alert_type="capital_rotation",
                severity="notable",
                domain=f"{from_node}->{to_node}",
                trigger_condition=rotation.get("hypothesis") or "Possible capital rotation",
                observed_value="possible_rotation",
                reference_value="no_rotation_signal",
                evidence_field_ids=(
                    _field_id(tool_id, f".pairs[{i}].inferred_capital_rotation.status"),
                ),
                source_tool_id=tool_id,
                component_status="ok",
                dedup_key=f"capital_rotation:{from_node}->{to_node}",
            )
        )
    return out


# Tool-level data_quality statuses that mean the evidence is not trustworthy enough to establish
# that anything cleared (a superset of the statuses ``cfi.analyst.tools`` uses to call a tool
# degraded or conflicting, plus ``missing``, the quality vocabulary of the domain services).
_UNTRUSTED_QUALITY = frozenset({"degraded", "partial", "stale", "conflicting", "missing"})


def _tool_quality_ok(data: dict[str, Any]) -> bool:
    quality = data.get("data_quality") or data.get("quality")
    status = quality.get("status") if isinstance(quality, dict) else None
    return not (isinstance(status, str) and status in _UNTRUSTED_QUALITY)


def _item_quality_ok(item: dict[str, Any]) -> bool:
    """Item-level ``data_quality`` must be present and ``ok`` (absent is not evidence)."""
    quality = item.get("data_quality")
    return isinstance(quality, dict) and quality.get("status") == "ok"


def cleared_dedup_keys(snapshot: Snapshot) -> frozenset[str]:
    """Dedup keys of flagged-state alerts (divergence / anomaly / capital_rotation) that this
    snapshot EXPLICITLY shows have cleared (Phase 52). A missing item, a failed or unavailable
    tool, an ``unavailable``/``None`` reading, degraded or conflicting quality: none of these is
    evidence of clearance, so none appears here and the alert keeps its status.

    Explicit clearance is, per type, the domain's own affirmative negative: divergence
    ``is_divergent is False`` (``None`` means unavailable) with both legs' data quality ``ok``;
    anomaly ``band == "normal"`` (``unavailable`` is not normal) with a usable component and
    ``ok`` data quality; capital rotation edge ``status == "no_rotation_signal"`` (``unavailable``
    is not a signal either way). A snapshot with ``has_conflicts`` clears nothing."""
    if snapshot.has_conflicts:
        return frozenset()
    cleared: set[str] = set()

    data = _tool_data(snapshot, ALERT_TYPE_TOOL_IDS["divergence"])
    if data is not None and _tool_quality_ok(data):
        for c in data.get("comparisons") or []:
            legs = (c.get("metric_a"), c.get("metric_b"))
            if (
                c.get("is_divergent") is False
                and c.get("comparison_id") is not None
                and all(isinstance(leg, dict) and _item_quality_ok(leg) for leg in legs)
            ):
                cleared.add(f"divergence:{c['comparison_id']}")

    data = _tool_data(snapshot, ALERT_TYPE_TOOL_IDS["anomaly"])
    if data is not None and _tool_quality_ok(data):
        for a in data.get("anomalies") or []:
            if (
                a.get("band") == "normal"
                and a.get("metric_id") is not None
                and a.get("status") not in _UNUSABLE_STATUSES
                and _item_quality_ok(a)
            ):
                cleared.add(f"anomaly:{a['metric_id']}")

    data = _tool_data(snapshot, ALERT_TYPE_TOOL_IDS["capital_rotation"])
    if data is not None and _tool_quality_ok(data):
        for p in data.get("pairs") or []:
            rotation = p.get("inferred_capital_rotation") or {}
            from_node = (p.get("from_node") or {}).get("node_id")
            to_node = (p.get("to_node") or {}).get("node_id")
            if (
                rotation.get("status") == "no_rotation_signal"
                and from_node is not None
                and to_node is not None
            ):
                cleared.add(f"capital_rotation:{from_node}->{to_node}")
    return frozenset(cleared)


def evaluate_regime_change(snapshot: Snapshot) -> list[AlertCandidate]:
    """regime_change: the current regime classification is always reported (one candidate, since
    there is one benchmark-asset regime); whether it is a *change* is decided by
    ``cfi.alerts.lifecycle.decide``. Severity is "elevated" when the regime engine's own reported
    confidence crosses the declared ``HIGH_CONFIDENCE_REGIME_THRESHOLD``, else "notable"."""
    tool_id = ALERT_TYPE_TOOL_IDS["regime_change"]
    data = _tool_data(snapshot, tool_id)
    if data is None:
        return []
    status = data.get("status")
    regime_id = data.get("regime_id")
    if status != "ok" or regime_id is None:
        return []
    severity = "notable"
    confidence = data.get("confidence")
    if confidence is not None:
        try:
            if Decimal(str(confidence)) >= Decimal(HIGH_CONFIDENCE_REGIME_THRESHOLD):
                severity = "elevated"
        except InvalidOperation:
            pass
    return [
        AlertCandidate(
            alert_type="regime_change",
            severity=severity,
            domain=str(data.get("asset") or "GLOBAL"),
            trigger_condition="Market regime classification",
            observed_value=str(regime_id),
            reference_value=None,
            evidence_field_ids=(_field_id(tool_id, ".regime_id"), _field_id(tool_id, ".status")),
            source_tool_id=tool_id,
            component_status=str(status),
            dedup_key=f"regime_change:{data.get('asset') or 'GLOBAL'}",
        )
    ]


EVALUATORS = (
    evaluate_institutional_flow,
    evaluate_whale_activity,
    evaluate_retail_activity,
    evaluate_derivatives,
    evaluate_liquidity,
    evaluate_macro,
    evaluate_market_structure,
    evaluate_divergence,
    evaluate_anomaly,
    evaluate_capital_rotation,
    evaluate_regime_change,
)


def evaluate_all(snapshot: Snapshot) -> list[AlertCandidate]:
    candidates: list[AlertCandidate] = []
    for evaluator in EVALUATORS:
        candidates.extend(evaluator(snapshot))
    return candidates
