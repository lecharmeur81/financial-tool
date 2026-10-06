"""Deterministic comparison of two persisted decision assessments (Phase 41).

``compare_assessments(previous, current)`` is a pure function of two ``sig.decision_assessment``
rows. It recalculates nothing: it reads the persisted stance, confidence, posture, coverage and the
persisted ``assessment`` JSON (the Phase 38.3 ``DecisionContext.deterministic_dict()``) and reports
what differs. It imports no rule function, queries no database, reads no clock and calls no
provider or model. Same two inputs always give the same result.

Six dimensions are compared, always in this order: stance, confidence, posture, evidence, coverage
(coverage, component availability and data-quality limitations) and risk. The classification is
``NO_CHANGE`` when none differs, the dimension's own label when exactly one differs, and
``MULTIPLE_CHANGES`` otherwise. A direction is reported per dimension only where the engine's own
orderings define one; nothing here is a market view or a prediction.

Which two rows are compared is decided by ``cfi.decision_history.history`` (same scope, adjacent by
``snapshot_id``, same methodology and parameter versions); this module compares what it is given.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from cfi.decision.universe import (
    BEARISH_FAMILY,
    BULLISH_FAMILY,
    CONFIDENCE_ORDER,
    RISK_ORDER,
    STANCE_STRENGTH,
    Confidence,
    Posture,
    RiskLevel,
    Stance,
)

__all__ = [
    "AssessmentChange",
    "ChangeDirection",
    "ChangeKind",
    "ComponentChange",
    "CoverageChange",
    "EvidenceChange",
    "EvidenceItemChange",
    "MalformedAssessmentError",
    "PersistedAssessment",
    "RiskChange",
    "ScalarChange",
    "compare_assessments",
]

_STRENGTH_ORDER = {"Missing": 0, "Weak": 1, "Moderate": 2, "Strong": 3}
_SIDES = ("supportive", "adverse", "neutral")


class MalformedAssessmentError(ValueError):
    """A persisted assessment lacks a field the Phase 40 contract guarantees."""


class ChangeKind(StrEnum):
    NO_CHANGE = "NO_CHANGE"
    STANCE_CHANGED = "STANCE_CHANGED"
    CONFIDENCE_CHANGED = "CONFIDENCE_CHANGED"
    POSTURE_CHANGED = "POSTURE_CHANGED"
    EVIDENCE_CHANGED = "EVIDENCE_CHANGED"
    COVERAGE_CHANGED = "COVERAGE_CHANGED"
    RISK_CHANGED = "RISK_CHANGED"
    MULTIPLE_CHANGES = "MULTIPLE_CHANGES"


class ChangeDirection(StrEnum):
    IMPROVED = "improved"
    DETERIORATED = "deteriorated"
    STRENGTHENED = "strengthened"
    WEAKENED = "weakened"
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    INSUFFICIENT_EVIDENCE = "insufficient evidence"


# --------------------------------------------------------------------------- input
@dataclass(frozen=True, slots=True)
class PersistedAssessment:
    """One ``sig.decision_assessment`` row, as the history layer needs it."""

    snapshot_id: int
    scope: str
    methodology_version: str
    parameter_version: str
    template_version: str
    snapshot_as_of: datetime
    created_at: datetime
    producer_hash_check: str
    decision_input_hash: str
    stance: str
    confidence: str
    posture: str
    coverage_available: int
    expected_domains: int
    conflict: bool
    assessment: Mapping[str, Any]


# --------------------------------------------------------------------------- output
@dataclass(frozen=True, slots=True)
class ScalarChange:
    previous: str
    current: str
    changed: bool
    direction: ChangeDirection

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous": self.previous,
            "current": self.current,
            "changed": self.changed,
            "direction": self.direction.value,
        }


@dataclass(frozen=True, slots=True)
class EvidenceItemChange:
    side: str
    domain: str
    change: str  # added / removed / changed
    previous: dict[str, Any] | None
    current: dict[str, Any] | None
    fields_changed: tuple[str, ...]
    strength_direction: ChangeDirection | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "domain": self.domain,
            "change": self.change,
            "previous": self.previous,
            "current": self.current,
            "fields_changed": list(self.fields_changed),
            "strength_direction": (
                None if self.strength_direction is None else self.strength_direction.value
            ),
        }


@dataclass(frozen=True, slots=True)
class EvidenceChange:
    changed: bool
    items: tuple[EvidenceItemChange, ...]
    conflict_previous: bool
    conflict_current: bool
    contradictions_added: tuple[str, ...]
    contradictions_removed: tuple[str, ...]
    direction: ChangeDirection

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "direction": self.direction.value,
            "items": [i.to_dict() for i in self.items],
            "conflict": {
                "previous": self.conflict_previous,
                "current": self.conflict_current,
                "changed": self.conflict_previous != self.conflict_current,
            },
            "contradictions_added": list(self.contradictions_added),
            "contradictions_removed": list(self.contradictions_removed),
        }


@dataclass(frozen=True, slots=True)
class ComponentChange:
    component: str
    previous: dict[str, Any]
    current: dict[str, Any]
    transition: str  # became_available / became_unavailable / state_changed

    def to_dict(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "transition": self.transition,
            "previous": self.previous,
            "current": self.current,
        }


@dataclass(frozen=True, slots=True)
class CoverageChange:
    changed: bool
    direction: ChangeDirection
    previous_available: int
    current_available: int
    previous_expected: int
    current_expected: int
    directional_became_available: tuple[str, ...]
    directional_became_unavailable: tuple[str, ...]
    context_became_available: tuple[str, ...]
    context_became_unavailable: tuple[str, ...]
    components: tuple[ComponentChange, ...]
    limitations_added: tuple[str, ...]
    limitations_removed: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed": self.changed,
            "direction": self.direction.value,
            "previous": {"available": self.previous_available, "expected": self.previous_expected},
            "current": {"available": self.current_available, "expected": self.current_expected},
            "directional_became_available": list(self.directional_became_available),
            "directional_became_unavailable": list(self.directional_became_unavailable),
            "context_became_available": list(self.context_became_available),
            "context_became_unavailable": list(self.context_became_unavailable),
            "components": [c.to_dict() for c in self.components],
            "limitations_added": list(self.limitations_added),
            "limitations_removed": list(self.limitations_removed),
        }


@dataclass(frozen=True, slots=True)
class RiskChange:
    dimension: str
    previous: str
    current: str
    direction: ChangeDirection

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "previous": self.previous,
            "current": self.current,
            "direction": self.direction.value,
        }


@dataclass(frozen=True, slots=True)
class AssessmentChange:
    kind: ChangeKind
    changed_dimensions: tuple[ChangeKind, ...]
    stance: ScalarChange
    confidence: ScalarChange
    posture: ScalarChange
    evidence: EvidenceChange
    coverage: CoverageChange
    risk_changed: bool
    risk_direction: ChangeDirection
    risk_max: ScalarChange
    risk_dimensions: tuple[RiskChange, ...]
    same_decision_input: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.kind.value,
            "changed_dimensions": [d.value for d in self.changed_dimensions],
            "same_decision_input": self.same_decision_input,
            "stance": self.stance.to_dict(),
            "confidence": self.confidence.to_dict(),
            "posture": self.posture.to_dict(),
            "evidence": self.evidence.to_dict(),
            "coverage": self.coverage.to_dict(),
            "risk": {
                "changed": self.risk_changed,
                "direction": self.risk_direction.value,
                "max": self.risk_max.to_dict(),
                "dimensions": [r.to_dict() for r in self.risk_dimensions],
            },
        }


# --------------------------------------------------------------------------- helpers
def _field(source: Mapping[str, Any], key: str, where: str) -> Any:
    if key not in source:
        raise MalformedAssessmentError(f"persisted assessment has no {where}{key!r}")
    return source[key]


def _result(row: PersistedAssessment) -> Mapping[str, Any]:
    """The engine's ``AssessmentResult`` inside the persisted ``DecisionContext`` dict
    (``assessment["assessment"]``)."""
    result = row.assessment.get("assessment")
    if not isinstance(result, Mapping):
        raise MalformedAssessmentError("persisted assessment has no 'assessment' result object")
    return result


def _strings(source: Mapping[str, Any], key: str) -> tuple[str, ...]:
    return tuple(str(v) for v in _field(source, key, "assessment."))


def _stance_direction(previous: Stance, current: Stance) -> ChangeDirection:
    if previous == current:
        return ChangeDirection.UNCHANGED
    if Stance.INSUFFICIENT in (previous, current):
        return ChangeDirection.INSUFFICIENT_EVIDENCE
    if (previous in BULLISH_FAMILY and current in BEARISH_FAMILY) or (
        previous in BEARISH_FAMILY and current in BULLISH_FAMILY
    ):
        return ChangeDirection.CHANGED  # opposite families: conviction magnitude is not comparable
    before, after = STANCE_STRENGTH[previous], STANCE_STRENGTH[current]
    if after > before:
        return ChangeDirection.STRENGTHENED
    if after < before:
        return ChangeDirection.WEAKENED
    return ChangeDirection.CHANGED


def _confidence_direction(previous: Confidence, current: Confidence) -> ChangeDirection:
    if previous == current:
        return ChangeDirection.UNCHANGED
    if Confidence.INSUFFICIENT in (previous, current):
        return ChangeDirection.INSUFFICIENT_EVIDENCE
    if CONFIDENCE_ORDER[current] > CONFIDENCE_ORDER[previous]:
        return ChangeDirection.STRENGTHENED
    return ChangeDirection.WEAKENED


def _risk_direction(previous: str, current: str) -> ChangeDirection:
    if previous == current:
        return ChangeDirection.UNCHANGED
    p, c = RiskLevel(previous), RiskLevel(current)
    if p not in RISK_ORDER or c not in RISK_ORDER:
        return ChangeDirection.CHANGED  # to or from "Not assessed": not an ordered move
    return (
        ChangeDirection.DETERIORATED if RISK_ORDER[c] > RISK_ORDER[p] else ChangeDirection.IMPROVED
    )


def _scalar(previous: str, current: str, direction: ChangeDirection) -> ScalarChange:
    return ScalarChange(previous, current, previous != current, direction)


# --------------------------------------------------------------------------- evidence
def _item_view(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "direction": item.get("direction"),
        "strength": item.get("strength"),
        "band": item.get("band"),
        "template_id": item.get("template_id"),
        "quality_flags": list(item.get("quality_flags") or ()),
    }


def _items_by_domain(assessment: Mapping[str, Any], side: str) -> dict[str, dict[str, Any]]:
    items = _field(assessment, side, "assessment.")
    return {str(i["domain"]): _item_view(i) for i in items}


def _compare_evidence(
    previous: PersistedAssessment, current: PersistedAssessment
) -> EvidenceChange:
    out: list[EvidenceItemChange] = []
    for side in _SIDES:
        before = _items_by_domain(_result(previous), side)
        after = _items_by_domain(_result(current), side)
        for domain in sorted(before.keys() | after.keys()):
            b, a = before.get(domain), after.get(domain)
            if b is None:
                out.append(EvidenceItemChange(side, domain, "added", None, a, (), None))
            elif a is None:
                out.append(EvidenceItemChange(side, domain, "removed", b, None, (), None))
            elif b != a:
                fields = tuple(k for k in b if b[k] != a[k])
                strength_dir: ChangeDirection | None = None
                if "strength" in fields:
                    strength_dir = (
                        ChangeDirection.STRENGTHENED
                        if _STRENGTH_ORDER.get(str(a["strength"]), 0)
                        > _STRENGTH_ORDER.get(str(b["strength"]), 0)
                        else ChangeDirection.WEAKENED
                    )
                out.append(EvidenceItemChange(side, domain, "changed", b, a, fields, strength_dir))
    p_contra = set(_strings(_result(previous), "contradictions"))
    c_contra = set(_strings(_result(current), "contradictions"))
    conflict_changed = previous.conflict != current.conflict
    changed = bool(out) or conflict_changed or p_contra != c_contra
    return EvidenceChange(
        changed=changed,
        items=tuple(out),
        conflict_previous=previous.conflict,
        conflict_current=current.conflict,
        contradictions_added=tuple(sorted(c_contra - p_contra)),
        contradictions_removed=tuple(sorted(p_contra - c_contra)),
        direction=ChangeDirection.CHANGED if changed else ChangeDirection.UNCHANGED,
    )


# --------------------------------------------------------------------------- coverage
def _component_states(assessment: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for reading in _field(assessment, "readings", "assessment."):
        out[str(reading["component"])] = {
            "status": reading.get("status"),
            "freshness": reading.get("freshness"),
            "quality_flags": list(reading.get("quality_flags") or ()),
        }
    return out


def _compare_coverage(
    previous: PersistedAssessment, current: PersistedAssessment
) -> CoverageChange:
    pa, ca = _result(previous), _result(current)
    p_missing, c_missing = set(_strings(pa, "missing")), set(_strings(ca, "missing"))
    p_ctx, c_ctx = set(_strings(pa, "missing_context")), set(_strings(ca, "missing_context"))
    p_lim, c_lim = set(_strings(pa, "limitations")), set(_strings(ca, "limitations"))

    p_comp, c_comp = _component_states(pa), _component_states(ca)
    components: list[ComponentChange] = []
    net_available = 0
    for name in sorted(p_comp.keys() | c_comp.keys()):
        b = p_comp.get(name, {"status": None, "freshness": None, "quality_flags": []})
        a = c_comp.get(name, {"status": None, "freshness": None, "quality_flags": []})
        if a == b:
            continue
        was, now = b["status"] == "ok", a["status"] == "ok"
        if now and not was:
            transition, net_available = "became_available", net_available + 1
        elif was and not now:
            transition, net_available = "became_unavailable", net_available - 1
        else:
            transition = "state_changed"
        components.append(ComponentChange(name, b, a, transition))

    expected_changed = previous.expected_domains != current.expected_domains
    delta = current.coverage_available - previous.coverage_available
    changed = bool(
        delta
        or expected_changed
        or p_missing != c_missing
        or p_ctx != c_ctx
        or p_lim != c_lim
        or components
    )
    if not changed:
        direction = ChangeDirection.UNCHANGED
    elif expected_changed:
        direction = ChangeDirection.CHANGED
    elif delta:
        direction = ChangeDirection.IMPROVED if delta > 0 else ChangeDirection.DETERIORATED
    elif net_available:
        direction = ChangeDirection.IMPROVED if net_available > 0 else ChangeDirection.DETERIORATED
    else:
        direction = ChangeDirection.CHANGED
    return CoverageChange(
        changed=changed,
        direction=direction,
        previous_available=previous.coverage_available,
        current_available=current.coverage_available,
        previous_expected=previous.expected_domains,
        current_expected=current.expected_domains,
        directional_became_available=tuple(sorted(p_missing - c_missing)),
        directional_became_unavailable=tuple(sorted(c_missing - p_missing)),
        context_became_available=tuple(sorted(p_ctx - c_ctx)),
        context_became_unavailable=tuple(sorted(c_ctx - p_ctx)),
        components=tuple(components),
        limitations_added=tuple(sorted(c_lim - p_lim)),
        limitations_removed=tuple(sorted(p_lim - c_lim)),
    )


# --------------------------------------------------------------------------- risk
def _risk_levels(assessment: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(r["dimension"]): str(r["level"]) for r in _field(assessment, "risks", "assessment.")
    }


def _compare_risk(
    previous: PersistedAssessment, current: PersistedAssessment
) -> tuple[bool, ChangeDirection, ScalarChange, tuple[RiskChange, ...]]:
    before, after = _risk_levels(_result(previous)), _risk_levels(_result(current))
    rows: list[RiskChange] = []
    for dim in sorted(before.keys() | after.keys()):
        b, a = (
            before.get(dim, RiskLevel.NOT_ASSESSED.value),
            after.get(dim, RiskLevel.NOT_ASSESSED.value),
        )
        if b != a:
            rows.append(RiskChange(dim, b, a, _risk_direction(b, a)))
    p_max = str(_field(_result(previous), "max_risk", "assessment."))
    c_max = str(_field(_result(current), "max_risk", "assessment."))
    max_change = _scalar(p_max, c_max, _risk_direction(p_max, c_max))
    changed = bool(rows) or max_change.changed
    worse = any(r.direction is ChangeDirection.DETERIORATED for r in rows)
    better = any(r.direction is ChangeDirection.IMPROVED for r in rows)
    if not changed:
        direction = ChangeDirection.UNCHANGED
    elif worse and not better:
        direction = ChangeDirection.DETERIORATED
    elif better and not worse:
        direction = ChangeDirection.IMPROVED
    else:
        direction = ChangeDirection.CHANGED
    return changed, direction, max_change, tuple(rows)


# --------------------------------------------------------------------------- the comparison
def compare_assessments(
    previous: PersistedAssessment, current: PersistedAssessment
) -> AssessmentChange:
    """Compare two persisted assessments of the same scope and the same methodology/parameter
    versions (the caller guarantees that; see ``cfi.decision_history.history``)."""
    p_stance, c_stance = Stance(previous.stance), Stance(current.stance)
    p_conf, c_conf = Confidence(previous.confidence), Confidence(current.confidence)
    p_post, c_post = Posture(previous.posture), Posture(current.posture)

    stance = _scalar(previous.stance, current.stance, _stance_direction(p_stance, c_stance))
    confidence = _scalar(
        previous.confidence, current.confidence, _confidence_direction(p_conf, c_conf)
    )
    posture = _scalar(
        previous.posture,
        current.posture,
        ChangeDirection.UNCHANGED if p_post == c_post else ChangeDirection.CHANGED,
    )
    evidence = _compare_evidence(previous, current)
    coverage = _compare_coverage(previous, current)
    risk_changed, risk_direction, risk_max, risk_rows = _compare_risk(previous, current)

    flags: Sequence[tuple[ChangeKind, bool]] = (
        (ChangeKind.STANCE_CHANGED, stance.changed),
        (ChangeKind.CONFIDENCE_CHANGED, confidence.changed),
        (ChangeKind.POSTURE_CHANGED, posture.changed),
        (ChangeKind.EVIDENCE_CHANGED, evidence.changed),
        (ChangeKind.COVERAGE_CHANGED, coverage.changed),
        (ChangeKind.RISK_CHANGED, risk_changed),
    )
    dims = tuple(kind for kind, hit in flags if hit)
    kind = (
        ChangeKind.NO_CHANGE
        if not dims
        else dims[0]
        if len(dims) == 1
        else ChangeKind.MULTIPLE_CHANGES
    )
    return AssessmentChange(
        kind=kind,
        changed_dimensions=dims,
        stance=stance,
        confidence=confidence,
        posture=posture,
        evidence=evidence,
        coverage=coverage,
        risk_changed=risk_changed,
        risk_direction=risk_direction,
        risk_max=risk_max,
        risk_dimensions=risk_rows,
        same_decision_input=previous.decision_input_hash == current.decision_input_hash,
    )
