"""Market Regime Engine read service (Phase 14).

Evidence categories (R2): the seven underlying scores/readings are each already a Calculated
Metric or Statistical Signal published by their own domain module; the regime label and
confidence produced here are the platform's first Regime Classification (L4) — "a labelled market
state produced by a versioned model, with confidence." Confidence measures how well the current
conditions satisfy the regime's own definition, never a probability of future price direction (see
``cfi.regime.classifier.CONFIDENCE_SEMANTIC_NOTE``). Nothing here is an AI Interpretation (L5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.divergence.adapters import Adapters
from cfi.regime import parameters as rp
from cfi.regime.classifier import (
    CONFIDENCE_SEMANTIC_NOTE,
    ClassificationResult,
    ConditionOutcome,
    classify,
)
from cfi.regime.history import (
    DurationResult,
    Episode,
    historical_examples,
    regime_duration,
)
from cfi.regime.snapshot import gather_snapshot
from cfi.regime.universe import (
    BENCHMARK_ASSET,
    HISTORICAL_LOOKBACK_DAYS,
    HISTORICAL_STEP_DAYS,
    MAX_DURATION_LOOKBACK_DAYS,
    MAX_HISTORICAL_EXAMPLES,
    MIN_EPISODE_SAMPLES,
    NOT_TRACKED,
    REGIME_IDS,
)

EVIDENCE_NOTE = (
    "The regime label and confidence are a Regime Classification (L4): a versioned, rule-based "
    "reading of already-published Calculated Metrics and Statistical Signals from the "
    "institutional, whale, retail, liquidity, derivatives, macro and market-structure modules. "
    "Confidence measures how well current conditions satisfy this regime's own definition — it "
    "is NOT a probability that price will rise or fall, and it is not a trading recommendation."
)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _outcome(o: ConditionOutcome) -> dict[str, Any]:
    return {
        "condition_id": o.condition_id,
        "label": o.label,
        "metric_key": o.metric_key,
        "weight": num(o.weight),
        "rationale": o.rationale,
        "value": num(o.value),
        "condition": o.condition,
    }


def _candidate(score: Any) -> dict[str, Any]:
    return {
        "regime_id": score.regime_id,
        "label": score.label,
        "status": score.status,
        "confidence": num(score.confidence),
        "available_weight": num(score.available_weight),
    }


@dataclass
class RegimeService:
    engine: Any

    def __post_init__(self) -> None:
        self.adapters = Adapters(self.engine)

    def catalog(self) -> dict[str, Any]:
        params = rp.parameters()
        return {
            "version": params.version,
            "evidence_note": EVIDENCE_NOTE,
            "confidence_semantic_note": CONFIDENCE_SEMANTIC_NOTE,
            "regime_ids": list(REGIME_IDS),
            "benchmark_asset": BENCHMARK_ASSET,
            "parameters": {
                "min_available_weight": num(params.min_available_weight),
                "min_confidence_assign": num(params.min_confidence_assign),
                "tie_margin": num(params.tie_margin),
                "hysteresis_margin": num(params.hysteresis_margin),
                "max_duration_lookback_days": MAX_DURATION_LOOKBACK_DAYS,
                "historical_lookback_days": HISTORICAL_LOOKBACK_DAYS,
                "historical_step_days": HISTORICAL_STEP_DAYS,
                "min_episode_samples": MIN_EPISODE_SAMPLES,
                "max_historical_examples": MAX_HISTORICAL_EXAMPLES,
            },
            "regimes": [
                {
                    "regime_id": d.regime_id,
                    "label": d.label,
                    "description": d.description,
                    "conditions": [
                        {
                            "condition_id": c.condition_id,
                            "label": c.label,
                            "metric_key": c.metric_key,
                            "comparator": c.comparator,
                            "weight": num(c.weight),
                            "rationale": c.rationale,
                            "threshold": num(c.threshold),
                            "threshold_high": num(c.threshold_high),
                            "expected": list(c.expected) if c.expected else None,
                        }
                        for c in d.conditions
                    ],
                }
                for d in params.regimes
            ],
            "not_tracked": list(NOT_TRACKED),
        }

    async def _classify_at(
        self, as_of: datetime, *, previous_regime_id: str | None = None
    ) -> ClassificationResult:
        """Point-in-time classification as it would have appeared on ``as_of`` — knowledge_time is
        pinned to the same instant, deliberately excluding any later-ingested revision (R4).

        ``previous_regime_id`` threads hysteresis (finding #4, ADR-0062) through: the caller
        supplies whichever regime it wants this day's classification to persist against, if it
        still qualifies and the challenger has not cleared the margin."""
        snapshot = await gather_snapshot(
            self.adapters, asset=BENCHMARK_ASSET, as_of=as_of, knowledge_time=as_of
        )
        return classify(snapshot, rp.parameters(), previous_regime_id=previous_regime_id)

    async def current(self, *, as_of: datetime, knowledge_time: datetime) -> dict[str, Any]:
        snapshot = await gather_snapshot(
            self.adapters, asset=BENCHMARK_ASSET, as_of=as_of, knowledge_time=knowledge_time
        )
        # Hysteresis (finding #4, ADR-0062): find out what yesterday's own classification was
        # (itself un-hysteresis'd, since it has no "day before that" to check here) and let today's
        # result persist against it rather than flipping on any margin at all.
        yesterday = await self._classify_at(as_of - timedelta(days=1))
        previous_regime_id = yesterday.regime_id if yesterday.status == "ok" else None
        result = classify(snapshot, rp.parameters(), previous_regime_id=previous_regime_id)

        if result.status == "insufficient_data":
            # No regime could even be evaluated (zero available data) — a backward walk would
            # only re-discover the same "insufficient_data" at every prior day, so it is skipped
            # rather than spending hundreds of redundant re-classifications on a known-empty
            # result (a documented performance short-circuit, ADR-0057).
            duration = DurationResult(0, False, None)
            examples: list[Episode] = []
        else:

            async def classify_at(candidate: datetime) -> tuple[str, Decimal | None]:
                # Threading the anchor day's own (possibly hysteresis-held) regime through the
                # backward walk means "does this regime still hold" is checked consistently with
                # hysteresis at every earlier day too, not just at the anchor (finding #4).
                r = await self._classify_at(candidate, previous_regime_id=result.regime_id)
                return r.regime_id, r.confidence

            duration = await regime_duration(
                classify_at,
                as_of=as_of,
                current_regime_id=result.regime_id,
                max_lookback_days=MAX_DURATION_LOOKBACK_DAYS,
            )
            examples = await historical_examples(
                classify_at,
                as_of=as_of,
                current_regime_id=result.regime_id,
                streak_since=duration.since or as_of,
                lookback_days=HISTORICAL_LOOKBACK_DAYS,
                step_days=HISTORICAL_STEP_DAYS,
                min_episode_samples=MIN_EPISODE_SAMPLES,
                max_examples=MAX_HISTORICAL_EXAMPLES,
            )

        return {
            "asset": BENCHMARK_ASSET,
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "evidence_note": EVIDENCE_NOTE,
            "regime_id": result.regime_id,
            "label": result.label,
            "confidence": num(result.confidence),
            "confidence_semantic_note": CONFIDENCE_SEMANTIC_NOTE,
            "status": result.status,
            "reason": result.reason,
            "held_by_hysteresis": result.held_by_hysteresis,
            "regime_start_date": _iso(duration.since),
            "regime_duration_days": duration.days,
            "regime_duration_capped": duration.capped,
            "contributing_metrics": [_outcome(o) for o in result.contributing],
            "contradicting_metrics": [_outcome(o) for o in result.contradicting],
            "historical_examples": [
                {
                    "start": _iso(e.start),
                    "end": _iso(e.end),
                    "sample_days": e.sample_days,
                    "peak_confidence": num(e.peak_confidence),
                }
                for e in examples
            ],
            "candidates": [_candidate(s) for s in result.candidates],
            "not_tracked": list(NOT_TRACKED),
        }
