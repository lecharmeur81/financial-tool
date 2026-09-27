"""Unit tests for cfi.similarity.search — candidate-date sampling, scoring via a stub ``gather_at``
callback, and de-duplicated top-N/distribution-sample selection. No database, no real snapshots —
mirrors the style of ``test_regime_history.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.similarity import parameters as sp
from cfi.similarity.scorer import SimilarityScore
from cfi.similarity.search import (
    ScoredCandidate,
    candidate_dates,
    gather_candidates,
    select_analogues,
)
from cfi.similarity.snapshot import MetricReading, SimilaritySnapshot

AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def _params(**overrides: object) -> sp.ParameterSet:
    base = sp.parameters()
    fields = {
        "version": base.version,
        "features": base.features,
        "min_available_weight": base.min_available_weight,
        "lookback_days": base.lookback_days,
        "step_days": base.step_days,
        "min_candidate_age_days": base.min_candidate_age_days,
        "min_gap_days": base.min_gap_days,
        "top_n_analogues": base.top_n_analogues,
        "max_distribution_sample": base.max_distribution_sample,
        "min_distribution_sample": base.min_distribution_sample,
        "forward_return_horizons_days": base.forward_return_horizons_days,
        "drawdown_window_days": base.drawdown_window_days,
    }
    fields.update(overrides)
    return sp.ParameterSet(**fields)  # type: ignore[arg-type]


def _snapshot(date: datetime) -> SimilaritySnapshot:
    return SimilaritySnapshot(asset="BTC", as_of=date, knowledge_time=date, metrics={})


def _scored(date: datetime, similarity: str) -> ScoredCandidate:
    score = SimilarityScore(
        status="ok",
        similarity=Decimal(similarity),
        available_weight=Decimal("1.00"),
        compared=(),
    )
    return ScoredCandidate(date=date, snapshot=_snapshot(date), score=score)


# --------------------------------------------------------------------------- candidate_dates


def test_candidate_dates_are_all_at_least_min_age_before_as_of() -> None:
    params = _params(min_candidate_age_days=14, lookback_days=60, step_days=7)
    dates = candidate_dates(as_of=AS_OF, params=params)
    assert dates
    assert all(d <= AS_OF - timedelta(days=14) for d in dates)


def test_candidate_dates_stay_within_the_lookback_window() -> None:
    params = _params(min_candidate_age_days=0, lookback_days=30, step_days=7)
    dates = candidate_dates(as_of=AS_OF, params=params)
    assert all(d >= AS_OF - timedelta(days=30) for d in dates)


def test_candidate_dates_are_weekly_spaced() -> None:
    params = _params(min_candidate_age_days=0, lookback_days=30, step_days=7)
    dates = candidate_dates(as_of=AS_OF, params=params)
    diffs = {(dates[i] - dates[i + 1]).days for i in range(len(dates) - 1)}
    assert diffs == {7}


# --------------------------------------------------------------------------- select_analogues


def test_select_analogues_picks_highest_similarity_first() -> None:
    params = _params(min_gap_days=1, top_n_analogues=2, max_distribution_sample=3)
    scored = [
        _scored(AS_OF - timedelta(days=100), "70.00"),
        _scored(AS_OF - timedelta(days=200), "95.00"),
        _scored(AS_OF - timedelta(days=300), "80.00"),
    ]
    top_n, distribution = select_analogues(scored, params=params)
    assert [c.score.similarity for c in top_n] == [Decimal("95.00"), Decimal("80.00")]
    assert len(distribution) == 3


def test_select_analogues_skips_candidates_within_min_gap_of_a_selected_one() -> None:
    params = _params(min_gap_days=30, top_n_analogues=5, max_distribution_sample=5)
    scored = [
        _scored(AS_OF - timedelta(days=100), "95.00"),
        _scored(AS_OF - timedelta(days=110), "94.00"),  # only 10 days from the one above — skipped
        _scored(AS_OF - timedelta(days=300), "80.00"),  # far enough — kept
    ]
    top_n, _distribution = select_analogues(scored, params=params)
    dates = {c.date for c in top_n}
    assert AS_OF - timedelta(days=100) in dates
    assert AS_OF - timedelta(days=110) not in dates
    assert AS_OF - timedelta(days=300) in dates


def test_distribution_sample_is_a_superset_of_top_n_capped_at_max() -> None:
    params = _params(min_gap_days=1, top_n_analogues=2, max_distribution_sample=3)
    scored = [_scored(AS_OF - timedelta(days=d), f"{90 - d}.00") for d in (10, 20, 30, 40, 50)]
    top_n, distribution = select_analogues(scored, params=params)
    assert len(top_n) == 2
    assert len(distribution) == 3
    assert set(c.date for c in top_n).issubset({c.date for c in distribution})


# --------------------------------------------------------------------------- gather_candidates


async def test_gather_candidates_calls_gather_at_with_the_candidates_own_date_only() -> None:
    """Look-ahead-bias test: each candidate must be gathered at ITS OWN date, never the query's
    later as_of — proven here by a stub that records every date it was called with and a query
    snapshot dated well after any candidate."""
    seen_dates: list[datetime] = []
    query_snapshot = SimilaritySnapshot(
        asset="BTC",
        as_of=AS_OF,
        knowledge_time=AS_OF,
        metrics={
            "institutional_score": MetricReading(status="ok", value=Decimal(10)),
        },
    )

    async def gather_at(date: datetime) -> SimilaritySnapshot:
        seen_dates.append(date)
        return SimilaritySnapshot(
            asset="BTC",
            as_of=date,
            knowledge_time=date,
            metrics={"institutional_score": MetricReading(status="ok", value=Decimal(10))},
        )

    params = _params(
        min_candidate_age_days=14,
        lookback_days=21,
        step_days=7,
        min_available_weight=Decimal("0.1"),
    )
    candidates = await gather_candidates(
        gather_at, query_snapshot=query_snapshot, as_of=AS_OF, params=params
    )
    assert seen_dates  # at least one candidate was gathered
    assert all(d <= AS_OF - timedelta(days=14) for d in seen_dates), (
        "a candidate must never be gathered at or after the query's own as_of minus the minimum "
        "candidate age — that would leak the query's own later state into a 'historical' analogue"
    )
    assert len(candidates) == len(seen_dates)
