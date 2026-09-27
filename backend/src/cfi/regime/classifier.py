"""The regime classifier itself (Phase 14): evaluates every regime's condition set against a
``RegimeSnapshot`` and picks the best-supported regime — or ``mixed_unclear`` when no regime is
both sufficiently and unambiguously satisfied. Confidence measures *how well current conditions
satisfy a regime's definition* — it is explicitly not, and must never be read as, a probability
that price will rise or fall (the user's own explicit instruction, restated in
``CONFIDENCE_SEMANTIC_NOTE`` below and in every API response that carries a confidence value).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cfi.regime.parameters import ConditionDef, ParameterSet, RegimeDefinition
from cfi.regime.snapshot import MetricReading, RegimeSnapshot

CONFIDENCE_SEMANTIC_NOTE = (
    "Confidence measures how well current, already-observed conditions satisfy this regime's own "
    "definition. It is NOT a probability that price will rise or fall, and it is not a trading "
    "recommendation."
)

MIXED_UNCLEAR = "mixed_unclear"


@dataclass(frozen=True, slots=True)
class ConditionOutcome:
    condition_id: str
    label: str
    metric_key: str
    weight: Decimal
    rationale: str
    matched: bool | None  # None = the underlying metric was unavailable/insufficient
    value: Decimal | None
    condition: str | None


@dataclass(frozen=True, slots=True)
class RegimeScore:
    regime_id: str
    label: str
    description: str
    status: str  # "ok" | "insufficient_data"
    confidence: Decimal | None
    available_weight: Decimal
    outcomes: tuple[ConditionOutcome, ...]

    @property
    def contributing(self) -> tuple[ConditionOutcome, ...]:
        return tuple(o for o in self.outcomes if o.matched is True)

    @property
    def contradicting(self) -> tuple[ConditionOutcome, ...]:
        return tuple(o for o in self.outcomes if o.matched is False)


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    regime_id: str
    label: str
    confidence: Decimal | None
    status: str  # "ok" | "insufficient_data"
    contributing: tuple[ConditionOutcome, ...]
    contradicting: tuple[ConditionOutcome, ...]
    candidates: tuple[RegimeScore, ...]  # every regime's own score, ranked, for transparency
    reason: str | None = None


def _evaluate_condition(cond: ConditionDef, snapshot: RegimeSnapshot) -> ConditionOutcome:
    reading: MetricReading | None = snapshot.metrics.get(cond.metric_key)
    if reading is None or reading.status != "ok":
        return ConditionOutcome(
            cond.condition_id,
            cond.label,
            cond.metric_key,
            cond.weight,
            cond.rationale,
            matched=None,
            value=None,
            condition=None,
        )
    if cond.comparator == "categorical":
        matched = (
            reading.condition is not None
            and cond.expected is not None
            and (reading.condition in cond.expected)
        )
        return ConditionOutcome(
            cond.condition_id,
            cond.label,
            cond.metric_key,
            cond.weight,
            cond.rationale,
            matched=matched,
            value=reading.value,
            condition=reading.condition,
        )
    if reading.value is None:
        return ConditionOutcome(
            cond.condition_id,
            cond.label,
            cond.metric_key,
            cond.weight,
            cond.rationale,
            matched=None,
            value=None,
            condition=reading.condition,
        )
    if cond.comparator == "gte":
        matched = cond.threshold is not None and reading.value >= cond.threshold
    elif cond.comparator == "lte":
        matched = cond.threshold is not None and reading.value <= cond.threshold
    elif cond.comparator == "between":
        matched = (
            cond.threshold is not None
            and cond.threshold_high is not None
            and cond.threshold <= reading.value <= cond.threshold_high
        )
    else:  # pragma: no cover — exhaustive Comparator Literal
        raise ValueError(f"Unknown comparator: {cond.comparator!r}")
    return ConditionOutcome(
        cond.condition_id,
        cond.label,
        cond.metric_key,
        cond.weight,
        cond.rationale,
        matched=matched,
        value=reading.value,
        condition=reading.condition,
    )


def evaluate_regime(
    definition: RegimeDefinition, snapshot: RegimeSnapshot, *, min_available_weight: Decimal
) -> RegimeScore:
    outcomes = tuple(_evaluate_condition(c, snapshot) for c in definition.conditions)
    available_weight = sum((o.weight for o in outcomes if o.matched is not None), Decimal(0))
    matched_weight = sum((o.weight for o in outcomes if o.matched is True), Decimal(0))
    if available_weight < min_available_weight:
        return RegimeScore(
            definition.regime_id,
            definition.label,
            definition.description,
            "insufficient_data",
            None,
            available_weight,
            outcomes,
        )
    confidence = (matched_weight / available_weight).quantize(Decimal("0.01"))
    return RegimeScore(
        definition.regime_id,
        definition.label,
        definition.description,
        "ok",
        confidence,
        available_weight,
        outcomes,
    )


def classify(snapshot: RegimeSnapshot, params: ParameterSet) -> ClassificationResult:
    scores = tuple(
        evaluate_regime(d, snapshot, min_available_weight=params.min_available_weight)
        for d in params.regimes
    )
    ok_scores = sorted(
        (s for s in scores if s.status == "ok" and s.confidence is not None),
        key=lambda s: s.confidence,  # type: ignore[arg-type,return-value]
        reverse=True,
    )
    if not ok_scores:
        return ClassificationResult(
            MIXED_UNCLEAR,
            "Mixed / Unclear",
            None,
            "insufficient_data",
            (),
            (),
            scores,
            reason="No regime could be evaluated: too little available data across every "
            "regime's defining conditions.",
        )
    top = ok_scores[0]
    second = ok_scores[1] if len(ok_scores) > 1 else None
    margin = None if second is None else top.confidence - second.confidence  # type: ignore[operator]
    is_ambiguous = margin is not None and margin < params.tie_margin
    top_qualifies = top.confidence is not None and top.confidence >= params.min_confidence_assign
    if top_qualifies and not is_ambiguous:
        return ClassificationResult(
            top.regime_id,
            top.label,
            top.confidence,
            "ok",
            top.contributing,
            top.contradicting,
            scores,
        )
    if is_ambiguous and second is not None:
        reason = (
            f"'{top.label}' ({top.confidence}) and '{second.label}' ({second.confidence}) are "
            f"within {params.tie_margin} of each other — no single regime is clearly dominant."
        )
    else:
        reason = (
            f"The closest match, '{top.label}', reached only {top.confidence} confidence — "
            f"below the {params.min_confidence_assign} assignment threshold."
        )
    return ClassificationResult(
        MIXED_UNCLEAR,
        "Mixed / Unclear",
        top.confidence,
        "ok",
        top.contributing,
        top.contradicting,
        scores,
        reason=reason,
    )
