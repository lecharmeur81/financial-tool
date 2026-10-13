"""Capital Rotation Engine read service (Phase 20).

Evidence categories (R2): every underlying series (per-asset market cap, the genuine global TOTAL
crypto market cap, stablecoin circulating supply, institutional ETF net flow, whale exchange net
flow, retail meme-trending count) is Observed Data or a Calculated Metric already published by its
own domain module, read through ``cfi.divergence.adapters.Adapters`` (reused unchanged, plus one
new method, ``asset_market_cap``). The market-share ratio computed here (``cfi.rotation.metrics.
share_series``) is a Calculated Metric (L2); its window direction, magnitude and historical
percentile (``cfi.divergence.metrics``, reused unchanged) are Calculated Metrics / Statistical
Signals (L2/L3).

**OBSERVED CAPITAL FLOW vs. INFERRED CAPITAL ROTATION (this phase's explicit instruction):** a
node's own market-share reading (direction, magnitude, percentile, duration) is OBSERVED — it is a
direct calculation over data this platform actually ingested. An edge between two nodes is never
more than an INFERENCE: ``cfi.divergence.capital_flow_map.classify_edge`` (Phase 13, reused
unchanged) only ever returns ``"possible_rotation"`` — never a bare "rotation happened" claim —
with ``evidence_class: "inferred"`` and hedged wording ("consistent with, but not proof of ...");
this module never overrides that wording or upgrades an edge to a stated fact.
``flow_corroboration`` (``cfi.rotation.metrics``, new this phase) is the evidence the user asked
for: whether OBSERVED
institutional ETF / whale exchange net-flow data for the same node moved the same direction as its
own share (supporting) or the opposite direction (contradicting) — still not proof the flow caused
the share move, only a second, independently observed data point the hypothesis can be checked
against.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from cfi.core.errors import NotFoundError
from cfi.divergence import metrics as m
from cfi.divergence.adapters import Adapters
from cfi.divergence.capital_flow_map import classify_edge
from cfi.institutional.universe import ETF_ASSETS
from cfi.liquidity.universe import TOTAL_SUBJECT
from cfi.rotation import metrics as rm
from cfi.rotation.universe import (
    EXCLUDED_PAIRS,
    INFORMATIONAL_ONLY,
    LARGE_CAP_ASSETS,
    LOAD_SPAN_DAYS,
    NODES,
    NODES_BY_ID,
    NOT_TRACKED,
    ROTATION_PARAMETERS_V1,
    WINDOW_DAYS_DEFAULT,
    WINDOW_DAYS_MAX,
    WINDOW_DAYS_MIN,
    NodeDef,
)
from cfi.whales.universe import WHALE_ASSETS

EVIDENCE_NOTE = (
    "Each node's own market-share reading (direction, magnitude, historical percentile) is "
    "OBSERVED CAPITAL FLOW — a direct calculation over data this platform ingested. An edge "
    "between two nodes is always an INFERRED CAPITAL ROTATION hypothesis, never a stated fact: "
    "this system never claims capital moved from one asset to another solely because one node's "
    "share increased while the other's decreased. 'flow_corroboration' checks the hypothesis "
    "against a second, independently observed data point (institutional ETF / whale exchange net "
    "flow) — supporting or contradicting it, never proving it."
)

# Nodes actually eligible for pairwise rotation classification: a node with no tracked data at all
# (fetch_key is None) can only ever produce an 'unavailable' edge against every other node, so
# including it in the full matrix would only add guaranteed-empty rows (R13: do not over-engineer).
# /pair still accepts such a node_id directly and reports its own 'unavailable' status honestly.
_MATRIX_ELIGIBLE: tuple[str, ...] = tuple(
    n.node_id for n in NODES if n.fetch_key is not None and n.node_id not in INFORMATIONAL_ONLY
)


def num(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _canonical(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


@dataclass
class RotationService:
    engine: Any
    _cache: dict[tuple[str, str | None], m.Series] = field(default_factory=dict, init=False)
    # Node readings reused within ONE ``matrix`` call (keyed by every input that affects a
    # reading); ``None`` outside ``matrix``, so direct ``pair`` calls always recompute.
    _reading_memo: dict[tuple[str, int, datetime, datetime], dict[str, Any]] | None = field(
        default=None, init=False
    )

    def __post_init__(self) -> None:
        self.adapters = Adapters(self.engine)

    # ------------------------------------------------------------------ catalog

    def catalog(self) -> dict[str, Any]:
        seen: set[tuple[str, str]] = set()
        excluded = []
        for a, b in EXCLUDED_PAIRS:
            pair = _canonical(a, b)
            if pair in seen:
                continue
            seen.add(pair)
            excluded.append({"from": pair[0], "to": pair[1]})
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "label": n.label,
                    "measurement_class": n.measurement_class,
                    "scope_note": n.scope_note,
                    "informational_only": n.node_id in INFORMATIONAL_ONLY,
                }
                for n in NODES
            ],
            "matrix_eligible_nodes": list(_MATRIX_ELIGIBLE),
            "excluded_pairs": sorted(excluded, key=lambda p: (p["from"], p["to"])),
            "parameters": {
                "window_days_default": WINDOW_DAYS_DEFAULT,
                "window_days_min": WINDOW_DAYS_MIN,
                "window_days_max": WINDOW_DAYS_MAX,
                "load_span_days": LOAD_SPAN_DAYS,
                "version": ROTATION_PARAMETERS_V1.version,
                "description": ROTATION_PARAMETERS_V1.description,
            },
            "evidence_note": EVIDENCE_NOTE,
            "not_tracked": list(NOT_TRACKED),
        }

    # ------------------------------------------------------------------ raw series fetch (cached)

    async def _cached(self, key: str, subject: str | None, fetch: Any) -> m.Series:
        cache_key = (key, subject)
        if cache_key not in self._cache:
            self._cache[cache_key] = await fetch()
        return self._cache[cache_key]

    async def _total_market_cap(self, as_of: datetime, knowledge_time: datetime) -> m.Series:
        return await self._cached(
            "total_market_cap", None, lambda: self.adapters.total_market_cap(as_of, knowledge_time)
        )

    async def _asset_market_cap(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> m.Series:
        return await self._cached(
            "asset_market_cap",
            asset,
            lambda: self.adapters.asset_market_cap(asset, as_of, knowledge_time),
        )

    async def _stablecoin_supply(
        self, subject: str, as_of: datetime, knowledge_time: datetime
    ) -> m.Series:
        return await self._cached(
            "stablecoin_supply",
            subject,
            lambda: self.adapters.stablecoin_supply(subject, as_of, knowledge_time),
        )

    # ------------------------------------------------------------------ node share series

    async def _node_series(
        self, node: NodeDef, as_of: datetime, knowledge_time: datetime
    ) -> tuple[m.Series, str | None]:
        """(market-share-or-growth series, unavailable_reason). ``unavailable_reason`` is only set
        when ``node`` has no tracked data at all (``fetch_key is None``) — the series is then
        empty and every downstream reading reports 'insufficient_data', never a fabricated 0."""
        if node.fetch_key is None:
            return [], node.scope_note
        if node.fetch_key == "asset_share":
            asset = node.asset or ""
            numerator = await self._asset_market_cap(asset, as_of, knowledge_time)
            denominator = await self._total_market_cap(as_of, knowledge_time)
            return rm.share_series(numerator, denominator), None
        if node.fetch_key == "large_caps_share":
            components = [
                await self._asset_market_cap(a, as_of, knowledge_time) for a in LARGE_CAP_ASSETS
            ]
            numerator = rm.sum_series(components)
            denominator = await self._total_market_cap(as_of, knowledge_time)
            return rm.share_series(numerator, denominator), None
        if node.fetch_key == "stablecoin_growth":
            return await self._stablecoin_supply(TOTAL_SUBJECT, as_of, knowledge_time), None
        if node.fetch_key == "stablecoin_share":
            symbol = node.asset or ""
            numerator = await self._stablecoin_supply(symbol, as_of, knowledge_time)
            denominator = await self._stablecoin_supply(TOTAL_SUBJECT, as_of, knowledge_time)
            return rm.share_series(numerator, denominator), None
        if node.fetch_key == "retail_meme_trending":
            return await self._cached(
                "retail_meme_trending",
                None,
                lambda: self.adapters.retail_meme_trending_count(as_of, knowledge_time),
            ), None
        raise AssertionError(f"unknown fetch_key {node.fetch_key!r}")

    # ------------------------------------------------------------------ flow corroboration inputs

    async def _flow_readings(
        self, node: NodeDef, window_days: int, as_of: datetime, knowledge_time: datetime
    ) -> tuple[m.WindowReading | None, m.WindowReading | None]:
        """OBSERVED institutional ETF / whale exchange net-flow window readings for ``node``'s own
        asset(s), or ``(None, None)`` when flow corroboration does not apply (no fetch_key, or a
        node — like a stablecoin share — with no institutional/whale flow data of its own)."""
        if node.fetch_key == "asset_share":
            assets = [node.asset] if node.asset else []
        elif node.fetch_key == "large_caps_share":
            assets = list(LARGE_CAP_ASSETS)
        else:
            return None, None
        inst_assets = [a for a in assets if a in ETF_ASSETS]
        whale_assets = [a for a in assets if a in WHALE_ASSETS]
        inst_reading = None
        if inst_assets:
            key = "ALL" if node.fetch_key == "large_caps_share" else inst_assets[0]
            series = await self._cached(
                "institutional_net_flow",
                key,
                lambda k=key: self.adapters.institutional_net_flow(k, as_of, knowledge_time),
            )
            inst_reading = m.window_reading(series, as_of, window_days)
        whale_reading = None
        if whale_assets:
            key = "ALL" if node.fetch_key == "large_caps_share" else whale_assets[0]
            series = await self._cached(
                "whale_net_flow",
                key,
                lambda k=key: self.adapters.whale_net_flow(k, as_of, knowledge_time),
            )
            whale_reading = m.window_reading(series, as_of, window_days)
        return inst_reading, whale_reading

    # ------------------------------------------------------------------ per-node reading

    async def _node_reading(
        self, node: NodeDef, window_days: int, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        memo = self._reading_memo
        if memo is None:
            return await self._compute_node_reading(node, window_days, as_of, knowledge_time)
        key = (node.node_id, window_days, as_of, knowledge_time)
        cached = memo.get(key)
        if cached is None:
            cached = await self._compute_node_reading(node, window_days, as_of, knowledge_time)
            memo[key] = cached
        # Hand every caller its own copy: ``pair`` pops ``_rolling`` from the dict it receives and
        # the result is returned to API callers, so the stored reading must never be shared or
        # mutated. The (read-only, frozen) rolling series itself is shared.
        return {k: (v if k == "_rolling" else deepcopy(v)) for k, v in cached.items()}

    async def _compute_node_reading(
        self, node: NodeDef, window_days: int, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        series, unavailable_reason = await self._node_series(node, as_of, knowledge_time)
        if unavailable_reason is not None:
            return {
                "node_id": node.node_id,
                "label": node.label,
                "measurement_class": "unavailable",
                "status": "unavailable",
                "reason": unavailable_reason,
                "direction": "unavailable",
            }
        lookback = max(1, LOAD_SPAN_DAYS - window_days)
        rolling = m.rolling_series(
            series, window_days=window_days, as_of=as_of, lookback_days=lookback
        )
        reading = m.window_reading(series, as_of, window_days)
        magnitude, percentile = m.magnitude_and_percentile(rolling)
        quality = m.quality_summary(series, as_of, window_days)
        return {
            "node_id": node.node_id,
            "label": node.label,
            "measurement_class": node.measurement_class,
            "scope_note": node.scope_note,
            "status": reading.status,
            "reason": reading.reason,
            "direction": reading.direction,
            "first_time": _iso(reading.first_time),
            "first_value": num(reading.first_value),
            "last_time": _iso(reading.last_time),
            "last_value": num(reading.last_value),
            "delta": num(reading.delta),
            "change_pct": num(reading.change_pct),
            "magnitude": num(magnitude),
            "historical_percentile": {
                "status": percentile.status,
                "reason": percentile.reason,
                "percentile": num(percentile.percentile),
                "sample_size": percentile.sample_size,
            },
            "data_quality": {
                "status": quality.status,
                "points_in_window": quality.points_in_window,
                "flagged_points": quality.flagged_points,
            },
            "_rolling": rolling,  # internal only, stripped before returning to callers
        }

    # ------------------------------------------------------------------ pair

    async def pair(
        self,
        *,
        from_node_id: str,
        to_node_id: str,
        window_days: int,
        as_of: datetime,
        knowledge_time: datetime,
    ) -> dict[str, Any]:
        for node_id in (from_node_id, to_node_id):
            if node_id not in NODES_BY_ID:
                raise NotFoundError(
                    f"No rotation node named {node_id!r} (known: {', '.join(sorted(NODES_BY_ID))})."
                )
        if from_node_id == to_node_id:
            raise NotFoundError("from_node_id and to_node_id must be different nodes.")
        canonical = _canonical(from_node_id, to_node_id)
        if canonical in EXCLUDED_PAIRS or (canonical[1], canonical[0]) in EXCLUDED_PAIRS:
            raise NotFoundError(
                f"{from_node_id!r} and {to_node_id!r} are excluded from pairwise rotation "
                "classification: one is a strict aggregate of the other, so comparing them would "
                "manufacture a 'rotation' out of arithmetic identity, never an independent "
                "observation."
            )
        window_days = max(WINDOW_DAYS_MIN, min(window_days, WINDOW_DAYS_MAX))
        from_node, to_node = NODES_BY_ID[from_node_id], NODES_BY_ID[to_node_id]

        reading_a = await self._node_reading(from_node, window_days, as_of, knowledge_time)
        reading_b = await self._node_reading(to_node, window_days, as_of, knowledge_time)
        roll_a, roll_b = reading_a.pop("_rolling", None), reading_b.pop("_rolling", None)

        dir_a, dir_b = reading_a["direction"], reading_b["direction"]
        edge = classify_edge(from_node, to_node, dir_a, dir_b)

        supporting: list[str] = []
        contradicting: list[str] = []
        duration_payload: dict[str, Any] | None = None
        episodes_payload: list[dict[str, Any]] = []
        if roll_a is not None and roll_b is not None:
            dur = m.duration(roll_a.directions, roll_b.directions, roll_a.dates)
            episodes = m.historical_examples(roll_a, roll_b, dur.days)
            duration_payload = {"days": dur.days, "capped": dur.capped, "since": _iso(dur.since)}
            episodes_payload = [
                {
                    "start": _iso(e.start),
                    "end": _iso(e.end),
                    "days": e.days,
                    "peak_abs_delta_from_node": num(e.peak_abs_delta_a),
                    "peak_percentile_from_node": num(e.peak_percentile_a),
                }
                for e in episodes
            ]

        if edge.status == "possible_rotation":
            inst_a, whale_a = await self._flow_readings(
                from_node, window_days, as_of, knowledge_time
            )
            inst_b, whale_b = await self._flow_readings(to_node, window_days, as_of, knowledge_time)
            check_a = rm.flow_corroboration(
                from_node.label, dir_a, institutional_reading=inst_a, whale_reading=whale_a
            )
            check_b = rm.flow_corroboration(
                to_node.label, dir_b, institutional_reading=inst_b, whale_reading=whale_b
            )
            supporting = check_a.supporting + check_b.supporting
            contradicting = check_a.contradicting + check_b.contradicting
            if check_a.status == "not_applicable" and check_b.status == "not_applicable":
                contradicting.append(
                    "No institutional ETF or whale exchange flow data is tracked for either node "
                    "in this pair — this hypothesis has no OBSERVED FLOW corroboration check "
                    "available."
                )

        return {
            "from_node": reading_a,
            "to_node": reading_b,
            "window_days": window_days,
            "as_of": _iso(as_of),
            "knowledge_time": _iso(knowledge_time),
            "observed_capital_flow": {
                "from_node_direction": dir_a,
                "to_node_direction": dir_b,
            },
            "inferred_capital_rotation": {
                "status": edge.status,
                "evidence_class": edge.evidence_class,
                "hypothesis": edge.hypothesis,
            },
            "duration": duration_payload,
            "historical_examples": episodes_payload,
            "flow_corroboration": {
                "supporting_evidence": supporting,
                "contradicting_evidence": contradicting,
            },
            "evidence_note": EVIDENCE_NOTE,
        }

    # ------------------------------------------------------------------ matrix

    async def matrix(
        self, *, window_days: int, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        self._cache.clear()
        # Every node appears in several pairs; compute each node's reading once per matrix call
        # and discard it when the call ends (normally or by exception).
        self._reading_memo = {}
        try:
            return await self._matrix(
                window_days=window_days, as_of=as_of, knowledge_time=knowledge_time
            )
        finally:
            self._reading_memo = None

    async def _matrix(
        self, *, window_days: int, as_of: datetime, knowledge_time: datetime
    ) -> dict[str, Any]:
        window_days = max(WINDOW_DAYS_MIN, min(window_days, WINDOW_DAYS_MAX))
        pairs = []
        node_ids = list(_MATRIX_ELIGIBLE)
        for i in range(len(node_ids)):
            for j in range(i + 1, len(node_ids)):
                a, b = node_ids[i], node_ids[j]
                canonical = _canonical(a, b)
                if canonical in EXCLUDED_PAIRS or (canonical[1], canonical[0]) in EXCLUDED_PAIRS:
                    continue
                pairs.append(
                    await self.pair(
                        from_node_id=a,
                        to_node_id=b,
                        window_days=window_days,
                        as_of=as_of,
                        knowledge_time=knowledge_time,
                    )
                )
        return {
            "as_of": _iso(as_of),
            "knowledge_time": _iso(knowledge_time),
            "window_days": window_days,
            "pairs": pairs,
            "evidence_note": EVIDENCE_NOTE,
            "not_tracked": list(NOT_TRACKED),
        }
