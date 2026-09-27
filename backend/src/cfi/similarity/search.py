"""Historical candidate search (Phase 15): sample historical dates, score each against the query
snapshot, and select a de-duplicated top set. Mirrors the backward-sampling-with-a-callback shape
``cfi.regime.history`` already established for Phase 14, generalized from "re-classify" to
"gather a 9-feature snapshot and score it".

Look-ahead discipline: every candidate date is at least ``min_candidate_age_days`` before the
query's own ``as_of`` (never a "historical" analogue that is effectively today), and each
candidate's own snapshot is gathered with ``as_of = knowledge_time = candidate_date`` — never the
query's later ``as_of`` — by the caller-supplied ``gather_at`` callback.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from cfi.similarity import parameters as sp
from cfi.similarity.scorer import SimilarityScore, score_pair
from cfi.similarity.snapshot import SimilaritySnapshot

GatherAt = Callable[[datetime], Awaitable[SimilaritySnapshot]]


@dataclass(frozen=True, slots=True)
class ScoredCandidate:
    date: datetime
    snapshot: SimilaritySnapshot
    score: SimilarityScore


def candidate_dates(*, as_of: datetime, params: sp.ParameterSet) -> list[datetime]:
    """Weekly-sampled historical dates, most recent first, each at least
    ``min_candidate_age_days`` before ``as_of`` and within ``lookback_days`` of it."""
    latest = as_of - timedelta(days=params.min_candidate_age_days)
    n_samples = params.lookback_days // params.step_days
    dates: list[datetime] = []
    for i in range(n_samples):
        candidate = latest - timedelta(days=params.step_days * i)
        if candidate < as_of - timedelta(days=params.lookback_days):
            break
        dates.append(candidate)
    return dates


async def gather_candidates(
    gather_at: GatherAt,
    *,
    query_snapshot: SimilaritySnapshot,
    as_of: datetime,
    params: sp.ParameterSet,
) -> list[ScoredCandidate]:
    """Score every sampled historical date against the query snapshot; dates whose comparison is
    ``insufficient_data`` are dropped entirely (never included with a misleadingly low score)."""
    out: list[ScoredCandidate] = []
    for date in candidate_dates(as_of=as_of, params=params):
        snapshot = await gather_at(date)
        score = score_pair(query_snapshot, snapshot, params)
        if score.status == "ok":
            out.append(ScoredCandidate(date=date, snapshot=snapshot, score=score))
    return out


def _similarity_key(c: ScoredCandidate) -> float:
    assert c.score.similarity is not None  # noqa: S101 — only "ok"-status candidates are scored
    return float(c.score.similarity)


def select_analogues(
    scored: list[ScoredCandidate], *, params: sp.ParameterSet
) -> tuple[list[ScoredCandidate], list[ScoredCandidate]]:
    """Greedily select the most similar dates, most-similar first, skipping any candidate within
    ``min_gap_days`` of one already selected (so results are not several consecutive weeks of the
    same episode). Returns ``(top_n, distribution_sample)`` — ``distribution_sample`` is a larger,
    equally de-duplicated superset of ``top_n`` used only for the forward-return/drawdown
    distribution, never for a single predicted value."""
    ranked = sorted(scored, key=_similarity_key, reverse=True)
    selected: list[ScoredCandidate] = []
    gap = timedelta(days=params.min_gap_days)
    for candidate in ranked:
        if len(selected) >= params.max_distribution_sample:
            break
        if any(abs((candidate.date - s.date).days) < gap.days for s in selected):
            continue
        selected.append(candidate)
    top_n = selected[: params.top_n_analogues]
    return top_n, selected
