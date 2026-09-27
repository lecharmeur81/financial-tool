"""Unit tests for cfi.similarity.scorer — the pure, no-I/O similarity-scoring function. Uses
hand-built ``SimilaritySnapshot``s (no database, no async), matching the same style as
``test_regime_classifier.py``."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from cfi.similarity import parameters as sp
from cfi.similarity.scorer import score_pair
from cfi.similarity.snapshot import MetricReading, SimilaritySnapshot

AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def _snapshot(**values: Decimal | None) -> SimilaritySnapshot:
    metrics = {
        feature_id: (
            MetricReading(status="unavailable")
            if values.get(feature_id) is None
            else MetricReading(status="ok", value=values[feature_id])
        )
        for feature_id in (
            "institutional_score",
            "whale_score",
            "retail_activity_score",
            "liquidity_score",
            "funding_annualised_7d_pct",
            "oi_change_7d_pct",
            "volatility_percentile",
            "market_structure_score",
            "macro_score",
        )
    }
    return SimilaritySnapshot(asset="BTC", as_of=AS_OF, knowledge_time=AS_OF, metrics=metrics)


_ALL_OK = {
    "institutional_score": Decimal(20),
    "whale_score": Decimal(20),
    "retail_activity_score": Decimal(40),
    "liquidity_score": Decimal(10),
    "funding_annualised_7d_pct": Decimal(5),
    "oi_change_7d_pct": Decimal(2),
    "volatility_percentile": Decimal(60),
    "market_structure_score": Decimal(15),
    "macro_score": Decimal(5),
}


def test_identical_snapshots_score_100() -> None:
    a = _snapshot(**_ALL_OK)
    b = _snapshot(**_ALL_OK)
    result = score_pair(a, b, sp.parameters())
    assert result.status == "ok"
    assert result.similarity == Decimal("100.00")
    assert result.available_weight == Decimal("1.00")


def test_more_different_snapshot_scores_lower() -> None:
    close = dict(_ALL_OK)
    close["institutional_score"] = Decimal(22)
    far = dict(_ALL_OK)
    far["institutional_score"] = Decimal(-80)

    query = _snapshot(**_ALL_OK)
    close_result = score_pair(query, _snapshot(**close), sp.parameters())
    far_result = score_pair(query, _snapshot(**far), sp.parameters())

    assert close_result.status == far_result.status == "ok"
    assert close_result.similarity is not None
    assert far_result.similarity is not None
    assert close_result.similarity > far_result.similarity


def test_only_common_ok_features_are_compared() -> None:
    partial_query: dict[str, Decimal | None] = dict(_ALL_OK)
    partial_query["macro_score"] = None
    partial_candidate: dict[str, Decimal | None] = dict(_ALL_OK)
    partial_candidate["whale_score"] = None

    result = score_pair(_snapshot(**partial_query), _snapshot(**partial_candidate), sp.parameters())
    compared_ids = {c.feature_id for c in result.compared}
    assert "macro_score" not in compared_ids
    assert "whale_score" not in compared_ids
    assert result.available_weight == Decimal("1.00") - Decimal("0.10") - Decimal("0.15")


def test_insufficient_data_when_available_weight_below_minimum() -> None:
    sparse_query = {k: (v if k == "institutional_score" else None) for k, v in _ALL_OK.items()}
    sparse_candidate = {k: (v if k == "institutional_score" else None) for k, v in _ALL_OK.items()}

    result = score_pair(_snapshot(**sparse_query), _snapshot(**sparse_candidate), sp.parameters())
    assert result.status == "insufficient_data"
    assert result.similarity is None
    assert result.reason is not None
