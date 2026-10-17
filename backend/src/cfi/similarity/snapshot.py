"""Gather a point-in-time 9-feature ``SimilaritySnapshot`` (Phase 15), reusing
``cfi.divergence.adapters.Adapters`` as a service factory exactly as ``cfi.regime.snapshot`` does
(ADR-0057) — each domain's own already-tested public service method enforces its own point-in-time
correctness (``available_at <= as_of``, ``ingested_at <= knowledge_time``); this module only
re-parses the already-serialized (string-encoded) values back into ``Decimal``, the same small
conversion every domain-composing module in this platform performs locally (see
``cfi.whales.service._institutional``, ``cfi.regime.snapshot``) rather than sharing a utility.

Feature set (ADR-0058): 7 of the 9 features are the same fields ``cfi.regime.snapshot`` already
reads (institutional_score, whale_score, retail_activity_score, liquidity_score,
volatility_percentile, market_structure_score, macro_score); this module is a separate,
self-contained copy rather than importing from ``cfi.regime`` — the two engines are independent
consumers of the same underlying domain services, and Phase 14's already-committed module is not
modified to serve this later phase (R13). The 2 new standalone fields (funding, open interest) come
from the same ``derivatives().asset()`` call ``cfi.regime.snapshot`` already makes for its own
``derivatives_health``/``derivatives_liquidation_event`` metrics.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.core.pit_memo import pit_read
from cfi.divergence.adapters import Adapters
from cfi.macro.queries import MacroQueries
from cfi.macro.service import MacroService

Status = str  # "ok" | "insufficient_data" | "unavailable"

FEATURE_IDS: tuple[str, ...] = (
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


@dataclass(frozen=True, slots=True)
class MetricReading:
    status: Status
    value: Decimal | None = None


@dataclass(frozen=True, slots=True)
class SimilaritySnapshot:
    asset: str
    as_of: datetime
    knowledge_time: datetime
    metrics: dict[str, MetricReading] = field(default_factory=dict)
    # Display-only extras, not used as similarity features themselves.
    volatility_annualized_pct: Decimal | None = None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _score_reading(payload: dict[str, Any], *, value_key: str = "value") -> MetricReading:
    status = payload.get("status", "unavailable")
    if status != "ok":
        fallback = "unavailable" if status == "unavailable" else "insufficient_data"
        return MetricReading(status=fallback)
    return MetricReading(status="ok", value=_decimal(payload.get(value_key)))


def _field_reading(payload: dict[str, Any], key: str) -> MetricReading:
    """For sections with no status of their own (``funding``, ``open_interest``) — a ``None``
    value means the underlying calculation had insufficient history, not that it is unavailable."""
    value = _decimal(payload.get(key))
    if value is None:
        return MetricReading(status="insufficient_data")
    return MetricReading(status="ok", value=value)


async def gather_snapshot(
    adapters: Adapters, *, asset: str, as_of: datetime, knowledge_time: datetime
) -> SimilaritySnapshot:
    """Fetch the current reading of every similarity feature. Each read goes through the owning
    domain's own already-tested public service method — nothing here queries the database
    directly (see module docstring)."""
    engine = adapters.engine
    institutional = await pit_read(
        "institutional.score",
        engine,
        asset,
        as_of,
        knowledge_time,
        call=lambda: adapters.institutional().score(
            asset=asset, as_of=as_of, knowledge_time=knowledge_time
        ),
    )
    whale = await pit_read(
        "whales.score",
        engine,
        asset,
        as_of,
        knowledge_time,
        call=lambda: adapters.whales().score(
            asset=asset, as_of=as_of, knowledge_time=knowledge_time
        ),
    )
    # Only the two Retail scores are consumed below, so skip the data-quality section (and its
    # per-source job queries); ``overview_score`` is otherwise identical to ``overview``.
    retail = await pit_read(
        "retail.overview",
        engine,
        as_of,
        knowledge_time,
        call=lambda: adapters.retail().overview_score(as_of=as_of, knowledge_time=knowledge_time),
    )
    liquidity = await pit_read(
        "liquidity.overview",
        engine,
        as_of,
        knowledge_time,
        call=lambda: adapters.liquidity().overview(as_of=as_of, knowledge_time=knowledge_time),
    )
    derivatives = await pit_read(
        "derivatives.asset",
        engine,
        asset,
        as_of,
        knowledge_time,
        call=lambda: adapters.derivatives().asset(
            asset=asset, as_of=as_of, knowledge_time=knowledge_time
        ),
    )
    # Only ``macro['score']`` is consumed below, so skip the data-quality section (and its
    # per-source job queries); ``overview_score`` is otherwise identical to ``overview``.
    macro = await pit_read(
        "macro.overview_score",
        engine,
        as_of,
        knowledge_time,
        call=lambda: MacroService(MacroQueries(adapters.engine)).overview_score(
            as_of=as_of, knowledge_time=knowledge_time
        ),
    )
    # Only the score, per-asset readings and breadth are consumed below, so skip the TOTAL-family,
    # ETH/BTC and data-quality sections (and their queries); ``overview_score`` is otherwise
    # identical to ``overview``.
    market_structure = await pit_read(
        "market_structure.overview",
        engine,
        as_of,
        knowledge_time,
        call=lambda: adapters.market_structure().overview_score(
            as_of=as_of, knowledge_time=knowledge_time
        ),
    )

    metrics: dict[str, MetricReading] = {
        "institutional_score": _score_reading(institutional),
        "whale_score": _score_reading(whale),
        "retail_activity_score": _score_reading(
            retail.get("activity_score", {}), value_key="score"
        ),
        "liquidity_score": _score_reading(liquidity.get("score", {}), value_key="score"),
        "macro_score": _score_reading(macro.get("score", {}), value_key="score"),
        "market_structure_score": _score_reading(
            market_structure.get("score", {}), value_key="score"
        ),
        "funding_annualised_7d_pct": _field_reading(
            derivatives.get("funding", {}), "annualised_7d_pct"
        ),
        "oi_change_7d_pct": _field_reading(derivatives.get("open_interest", {}), "change_7d_pct"),
    }

    asset_ms = market_structure.get("assets", {}).get(asset)
    volatility = (asset_ms or {}).get("volatility")
    volatility_annualized: Decimal | None = None
    # Kept as two branches (not combined with `or`) so mypy narrows `volatility` to non-None in
    # the branches below — a combined condition loses that narrowing (see cfi.regime.snapshot).
    if volatility is None or volatility.get("status") != "ok":  # noqa: SIM114
        metrics["volatility_percentile"] = MetricReading(status="unavailable")
    elif volatility.get("percentile") is None:
        metrics["volatility_percentile"] = MetricReading(status="unavailable")
    else:
        metrics["volatility_percentile"] = MetricReading(
            status="ok", value=_decimal(volatility.get("percentile"))
        )
        volatility_annualized = _decimal(volatility.get("annualized_pct"))

    return SimilaritySnapshot(
        asset=asset,
        as_of=as_of,
        knowledge_time=knowledge_time,
        metrics=metrics,
        volatility_annualized_pct=volatility_annualized,
    )
