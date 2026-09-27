"""Historical Similarity Engine read service (Phase 15).

Evidence categories (R2): the similarity score is a Statistical Signal (L3) computed over
already-published Calculated Metrics from the institutional, whale, retail, liquidity, derivatives,
market-structure and macro modules (see ``cfi.similarity.scorer``). Each analogue's regime label is
a citation of Phase 14's own already-computed Regime Classification (L4) for that date, not a new
classification performed here. Forward returns, maximum drawdown and volatility are Calculated
Metrics (L2) about what actually happened after each historical analogue — never a forecast, and
never displayed before they would genuinely have been knowable (R4, this phase's explicit
instruction).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.divergence.adapters import Adapters
from cfi.market.sources import VENUES
from cfi.market.universe import ohlcv_dataset_id
from cfi.market_structure.metrics import Bar, bars_from_rows
from cfi.regime import parameters as regime_parameters
from cfi.regime.classifier import classify as classify_regime
from cfi.regime.snapshot import gather_snapshot as gather_regime_snapshot
from cfi.similarity import parameters as sp
from cfi.similarity.outcomes import (
    Distribution,
    build_distribution,
    forward_return,
    max_drawdown,
)
from cfi.similarity.scorer import FeatureComparison
from cfi.similarity.search import ScoredCandidate, gather_candidates, select_analogues
from cfi.similarity.snapshot import SimilaritySnapshot, gather_snapshot
from cfi.similarity.universe import BENCHMARK_ASSET, NOT_TRACKED

EVIDENCE_NOTE = (
    "The similarity score is a Statistical Signal (L3): a documented, fixed-normalization distance "
    "between the current 9-feature market state and a sampled historical date's own state, each "
    "read from already-published Calculated Metrics. It is NOT a Regime Classification and NOT a "
    "prediction. Each analogue's regime label cites Phase 14's own classification for that date. "
    "Forward returns and maximum drawdown are what actually happened after that date — realized "
    "outcomes, never a forecast — and are shown only once genuinely knowable as of this query's "
    "own as_of."
)

_VENUE = VENUES["coinbase"]
_OHLCV_DATASET_ID = ohlcv_dataset_id(_VENUE.quote, "1d")
_BAR_FETCH_BUFFER = timedelta(days=5)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _comparison(c: FeatureComparison) -> dict[str, Any]:
    return {
        "feature_id": c.feature_id,
        "weight": num(c.weight),
        "query_value": num(c.query_value),
        "candidate_value": num(c.candidate_value),
        "query_normalized": num(c.query_normalized),
        "candidate_normalized": num(c.candidate_normalized),
        "abs_diff_normalized": num(c.abs_diff_normalized),
    }


def _distribution(d: Distribution) -> dict[str, Any]:
    return {
        "horizon_days": d.horizon_days,
        "status": d.status,
        "count": d.count,
        "min_pct": num(d.min_pct),
        "p25_pct": num(d.p25_pct),
        "median_pct": num(d.median_pct),
        "p75_pct": num(d.p75_pct),
        "max_pct": num(d.max_pct),
        "reason": d.reason,
    }


@dataclass
class SimilarityService:
    engine: Any

    def __post_init__(self) -> None:
        self.adapters = Adapters(self.engine)

    def catalog(self) -> dict[str, Any]:
        params = sp.parameters()
        return {
            "version": params.version,
            "evidence_note": EVIDENCE_NOTE,
            "benchmark_asset": BENCHMARK_ASSET,
            "parameters": {
                "min_available_weight": num(params.min_available_weight),
                "lookback_days": params.lookback_days,
                "step_days": params.step_days,
                "min_candidate_age_days": params.min_candidate_age_days,
                "min_gap_days": params.min_gap_days,
                "top_n_analogues": params.top_n_analogues,
                "max_distribution_sample": params.max_distribution_sample,
                "min_distribution_sample": params.min_distribution_sample,
                "forward_return_horizons_days": list(params.forward_return_horizons_days),
                "drawdown_window_days": params.drawdown_window_days,
            },
            "features": [
                {
                    "feature_id": f.feature_id,
                    "label": f.label,
                    "weight": num(f.weight),
                    "normalization": f.normalization,
                    "unit": f.unit,
                    "evidence": f.evidence,
                    "clamp_min": num(f.clamp_min),
                    "clamp_max": num(f.clamp_max),
                }
                for f in params.features
            ],
            "not_tracked": list(NOT_TRACKED),
        }

    async def _regime_at(self, as_of: datetime) -> dict[str, Any]:
        snapshot = await gather_regime_snapshot(
            self.adapters, asset=BENCHMARK_ASSET, as_of=as_of, knowledge_time=as_of
        )
        result = classify_regime(snapshot, regime_parameters.parameters())
        return {
            "regime_id": result.regime_id,
            "label": result.label,
            "confidence": num(result.confidence),
            "status": result.status,
        }

    async def _bars(self, *, start: datetime, as_of: datetime) -> list[Bar]:
        queries = self.adapters.market()
        instrument = _VENUE.instruments.get(BENCHMARK_ASSET)
        if instrument is None:
            return []
        series_id = await queries.series_id(_OHLCV_DATASET_ID, instrument)
        if series_id is None:
            return []
        rows = await queries.bars(
            series_id,
            _VENUE.provider_id,
            start - _BAR_FETCH_BUFFER,
            as_of + timedelta(seconds=1),
            as_of,
        )
        return bars_from_rows(rows)

    async def _analogue(
        self,
        candidate: ScoredCandidate,
        *,
        bars: list[Bar],
        as_of: datetime,
        params: sp.ParameterSet,
    ) -> dict[str, Any]:
        regime = await self._regime_at(candidate.date)
        forward_returns = [
            forward_return(bars, anchor=candidate.date, horizon_days=h, as_of=as_of)
            for h in params.forward_return_horizons_days
        ]
        drawdown = max_drawdown(
            bars, anchor=candidate.date, window_days=params.drawdown_window_days, as_of=as_of
        )
        volatility = candidate.snapshot.volatility_annualized_pct
        return {
            "date": _iso(candidate.date),
            "similarity_score": num(candidate.score.similarity),
            "available_weight": num(candidate.score.available_weight),
            "regime": regime,
            "forward_returns": [
                {
                    "horizon_days": fr.horizon_days,
                    "status": fr.status,
                    "value_pct": num(fr.value_pct),
                    "reason": fr.reason,
                }
                for fr in forward_returns
            ],
            "max_drawdown": {
                "window_days": drawdown.window_days,
                "status": drawdown.status,
                "value_pct": num(drawdown.value_pct),
                "partial": drawdown.partial,
                "reason": drawdown.reason,
            },
            "volatility_annualized_pct": num(volatility),
            "compared_features": [_comparison(c) for c in candidate.score.compared],
        }

    async def current(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        params = sp.parameters()
        query_snapshot = await gather_snapshot(
            self.adapters, asset=BENCHMARK_ASSET, as_of=as_of, knowledge_time=knowledge_time
        )
        query_available_weight = sum(
            (
                f.weight
                for f in params.features
                if query_snapshot.metrics[f.feature_id].status == "ok"
            ),
            Decimal(0),
        )
        base_response: dict[str, Any] = {
            "asset": BENCHMARK_ASSET,
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "evidence_note": EVIDENCE_NOTE,
            "not_tracked": list(NOT_TRACKED),
        }

        if query_available_weight < params.min_available_weight:
            return {
                **base_response,
                "status": "insufficient_data",
                "reason": f"only {query_available_weight} of the required "
                f"{params.min_available_weight} feature weight was available for the query date",
                "analogues": [],
                "distribution": [],
            }

        async def gather_at(date: datetime) -> SimilaritySnapshot:
            return await gather_snapshot(
                self.adapters, asset=BENCHMARK_ASSET, as_of=date, knowledge_time=date
            )

        scored = await gather_candidates(
            gather_at, query_snapshot=query_snapshot, as_of=as_of, params=params
        )
        if not scored:
            return {
                **base_response,
                "status": "insufficient_data",
                "reason": "no historical candidate had enough comparable feature weight",
                "analogues": [],
                "distribution": [],
            }

        top_n, distribution_sample = select_analogues(scored, params=params)
        earliest = min(c.date for c in distribution_sample)
        bars = await self._bars(start=earliest, as_of=as_of)

        top_n_dates = {c.date for c in top_n}
        analogues = [await self._analogue(c, bars=bars, as_of=as_of, params=params) for c in top_n]
        distribution_pool = [
            await self._analogue(c, bars=bars, as_of=as_of, params=params)
            for c in distribution_sample
            if c.date not in top_n_dates
        ]
        all_rows = analogues + distribution_pool
        distribution = []
        for horizon in params.forward_return_horizons_days:
            values = [
                Decimal(row_fr["value_pct"])
                for row in all_rows
                for row_fr in row["forward_returns"]
                if row_fr["horizon_days"] == horizon
                and row_fr["status"] == "ok"
                and row_fr["value_pct"] is not None
            ]
            distribution.append(
                _distribution(
                    build_distribution(
                        values, horizon_days=horizon, min_sample=params.min_distribution_sample
                    )
                )
            )

        return {
            **base_response,
            "status": "ok",
            "query_available_weight": num(query_available_weight),
            "analogues": analogues,
            "distribution": distribution,
            "candidates_evaluated": len(scored),
            "candidates_selected_for_distribution": len(distribution_sample),
        }
