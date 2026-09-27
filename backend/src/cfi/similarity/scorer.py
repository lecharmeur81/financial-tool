"""Pure similarity scoring (Phase 15) — no I/O, no historical-date-specific behavior, so it cannot
itself be a source of look-ahead leakage: it only compares two already-gathered snapshots.

Methodology (documented, ADR-0058): every feature value is normalized onto a common 0..100 scale
using fixed, per-feature bounds (``cfi.similarity.parameters.normalize`` — never data-derived).
Only features where BOTH the query snapshot and the candidate snapshot are ``"ok"`` are compared;
each such feature contributes ``weight * (difference)^2`` to a weighted mean-squared difference,
which is then square-rooted (a weighted RMSE, 0..100 scale since normalized values are 0..100) and
subtracted from 100 to give a similarity score, also on a 0..100 scale (100 = identical normalized
profile across every compared feature). If the compared features' combined weight falls below
``min_available_weight``, the pair is not scored at all (``status="insufficient_data"``) rather
than assigning a misleadingly precise similarity from too little evidence — the same discipline
``cfi.regime.classifier`` already applies to confidence.

This is a Statistical Signal (L3), not a Regime Classification and not an AI Interpretation: it
measures how close two dates' feature profiles are, nothing about which direction price moved or
will move.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from cfi.similarity import parameters as sp
from cfi.similarity.snapshot import SimilaritySnapshot


@dataclass(frozen=True, slots=True)
class FeatureComparison:
    feature_id: str
    weight: Decimal
    query_value: Decimal
    candidate_value: Decimal
    query_normalized: Decimal
    candidate_normalized: Decimal
    abs_diff_normalized: Decimal


@dataclass(frozen=True, slots=True)
class SimilarityScore:
    status: str  # "ok" | "insufficient_data"
    similarity: Decimal | None
    available_weight: Decimal
    compared: tuple[FeatureComparison, ...]
    reason: str | None = None


def score_pair(
    query: SimilaritySnapshot, candidate: SimilaritySnapshot, params: sp.ParameterSet
) -> SimilarityScore:
    compared: list[FeatureComparison] = []
    available_weight = Decimal(0)
    weighted_sq_diff = Decimal(0)

    for feature in params.features:
        q = query.metrics.get(feature.feature_id)
        c = candidate.metrics.get(feature.feature_id)
        if q is None or c is None or q.status != "ok" or c.status != "ok":
            continue
        if q.value is None or c.value is None:
            continue
        q_norm = sp.normalize(q.value, feature)
        c_norm = sp.normalize(c.value, feature)
        diff = q_norm - c_norm
        compared.append(
            FeatureComparison(
                feature_id=feature.feature_id,
                weight=feature.weight,
                query_value=q.value,
                candidate_value=c.value,
                query_normalized=q_norm,
                candidate_normalized=c_norm,
                abs_diff_normalized=abs(diff),
            )
        )
        available_weight += feature.weight
        weighted_sq_diff += feature.weight * diff * diff

    if available_weight < params.min_available_weight:
        return SimilarityScore(
            status="insufficient_data",
            similarity=None,
            available_weight=available_weight,
            compared=tuple(compared),
            reason=f"only {available_weight} of the required "
            f"{params.min_available_weight} feature weight was available on both dates",
        )

    rmse = (weighted_sq_diff / available_weight).sqrt()
    similarity = max(Decimal(0), Decimal(100) - rmse)
    return SimilarityScore(
        status="ok",
        similarity=similarity.quantize(Decimal("0.01")),
        available_weight=available_weight,
        compared=tuple(compared),
    )
