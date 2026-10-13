"""Gather a point-in-time ``RegimeSnapshot`` from the seven existing domain scores/readings
(Phase 14), reusing ``cfi.divergence.adapters.Adapters`` as a service factory (it already
constructs every domain's ``*Service(queries)`` the same way ``cfi.whales.service`` composes
``InstitutionalService`` internally — see ADR-0057) rather than re-implementing any of them.

Every domain service's own public async method (``score()``/``overview()``/``asset()``) already
enforces point-in-time correctness (``available_at <= as_of``, ``ingested_at <= knowledge_time``);
this module only reads the already-serialized (string-encoded) values back into ``Decimal``, the
same conversion ``cfi.whales.service._institutional`` already performs on
``InstitutionalService.score()``'s own output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.divergence.adapters import Adapters
from cfi.macro.queries import MacroQueries
from cfi.macro.service import MacroService

Status = str  # "ok" | "insufficient_data" | "unavailable"


@dataclass(frozen=True, slots=True)
class MetricReading:
    status: Status
    value: Decimal | None = None
    condition: str | None = None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class RegimeSnapshot:
    asset: str
    as_of: datetime
    knowledge_time: datetime
    metrics: dict[str, MetricReading] = field(default_factory=dict)


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


async def gather_snapshot(
    adapters: Adapters, *, asset: str, as_of: datetime, knowledge_time: datetime
) -> RegimeSnapshot:
    """Fetch the current reading of every metric a regime condition can reference. Each read goes
    through the owning domain's own already-tested public service method — nothing here queries
    the database directly (see module docstring)."""
    institutional = await adapters.institutional().score(
        asset=asset, as_of=as_of, knowledge_time=knowledge_time
    )
    whale = await adapters.whales().score(asset=asset, as_of=as_of, knowledge_time=knowledge_time)
    retail = await adapters.retail().overview(as_of=as_of, knowledge_time=knowledge_time)
    liquidity = await adapters.liquidity().overview(as_of=as_of, knowledge_time=knowledge_time)
    derivatives = await adapters.derivatives().asset(
        asset=asset, as_of=as_of, knowledge_time=knowledge_time
    )
    # Only ``macro['score']`` is consumed below, so skip the data-quality section (and its
    # per-source job queries); ``overview_score`` is otherwise identical to ``overview``.
    macro = await MacroService(MacroQueries(adapters.engine)).overview_score(
        as_of=as_of, knowledge_time=knowledge_time
    )
    market_structure = await adapters.market_structure().overview(
        as_of=as_of, knowledge_time=knowledge_time
    )

    metrics: dict[str, MetricReading] = {
        "institutional_score": _score_reading(institutional),
        "whale_score": _score_reading(whale),
        "retail_activity_score": _score_reading(
            retail.get("activity_score", {}), value_key="score"
        ),
        "retail_speculation_score": _score_reading(
            retail.get("speculation_score", {}), value_key="score"
        ),
        "liquidity_score": _score_reading(liquidity.get("score", {}), value_key="score"),
        "derivatives_health": _score_reading(derivatives.get("score", {}), value_key="health"),
        "macro_score": _score_reading(macro.get("score", {}), value_key="score"),
        "market_structure_score": _score_reading(
            market_structure.get("score", {}), value_key="score"
        ),
    }

    asset_ms = market_structure.get("assets", {}).get(asset)
    trend = (asset_ms or {}).get("trend")
    rsi = (asset_ms or {}).get("rsi")
    volatility = (asset_ms or {}).get("volatility")
    breadth = market_structure.get("market_breadth")

    metrics["btc_trend"] = (
        MetricReading(status="unavailable")
        if trend is None or trend.get("status") != "ok"
        else MetricReading(status="ok", condition=trend.get("condition"))
    )
    metrics["btc_rsi"] = (
        MetricReading(status="unavailable")
        if rsi is None or rsi.get("status") != "ok"
        else MetricReading(
            status="ok", value=_decimal(rsi.get("value")), condition=rsi.get("condition")
        )
    )
    # Kept as two branches (not combined with `or`) so mypy narrows `volatility` to non-None in
    # the branches below — a combined condition loses that narrowing (see snapshot.py history).
    if volatility is None or volatility.get("status") != "ok":  # noqa: SIM114
        metrics["btc_volatility_percentile"] = MetricReading(status="unavailable")
    elif volatility.get("percentile") is None:
        metrics["btc_volatility_percentile"] = MetricReading(status="unavailable")
    else:
        metrics["btc_volatility_percentile"] = MetricReading(
            status="ok",
            value=_decimal(volatility.get("percentile")),
            condition=volatility.get("condition"),
        )
    metrics["market_breadth"] = (
        MetricReading(status="unavailable")
        if breadth is None or breadth.get("status") != "ok"
        else MetricReading(status="ok", condition=breadth.get("condition"))
    )

    liquidation = next(
        (
            c
            for c in derivatives.get("conditions", [])
            if c.get("condition_id") == "liquidation_event"
        ),
        None,
    )
    metrics["derivatives_liquidation_event"] = (
        MetricReading(status="unavailable")
        if liquidation is None or liquidation.get("state") == "unknown"
        else MetricReading(status="ok", condition=liquidation.get("state"))
    )

    return RegimeSnapshot(asset=asset, as_of=as_of, knowledge_time=knowledge_time, metrics=metrics)
