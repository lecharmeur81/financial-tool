"""The Capital Flow Map (Phase 13's explicit node chain) — node definitions and the pure edge
classification between OBSERVED FLOW (each node's own reading) and INFERRED ROTATION (a hedged,
never-stated-as-fact hypothesis about adjacent nodes moving in opposite directions).

R1/R3 discipline: an edge is only ever a hypothesis, never a claim. Wording always says "consistent
with, not proof of" and the field ``evidence_class`` is always ``"inferred"`` for a rotation edge —
mirroring R5's entity-classification evidence-class discipline applied here to a flow claim instead
of an actor identity claim.
"""

from __future__ import annotations

from dataclasses import dataclass

from cfi.divergence.universe import NOT_TRACKED


@dataclass(frozen=True, slots=True)
class NodeDef:
    node_id: str
    label: str
    fetch_key: str | None  # None => no tracked data for this node at all
    asset: str | None
    measurement_class: str  # observed / proxy / unavailable
    scope_note: str


NODES: tuple[NodeDef, ...] = (
    NodeDef(
        "institutions",
        "Institutions",
        "institutional_net_flow",
        "ALL",
        "observed",
        "Aggregate institutional US spot ETF net flow across all 4 tracked ETF assets "
        "(BTC/ETH/SOL/XRP).",
    ),
    NodeDef(
        "whales",
        "Whales",
        "whale_net_flow",
        "ALL",
        "observed",
        "Aggregate whale exchange net flow across BTC and ETH (the only tracked whale assets).",
    ),
    NodeDef(
        "liquidity",
        "Liquidity",
        "stablecoin_supply_total",
        None,
        "observed",
        "Combined TOTAL stablecoin supply (USDT+USDC).",
    ),
    NodeDef("btc", "BTC", "price", "BTC", "observed", "Coinbase daily close."),
    NodeDef("eth", "ETH", "price", "ETH", "observed", "Coinbase daily close."),
    NodeDef("sol", "SOL", "price", "SOL", "observed", "Coinbase daily close."),
    NodeDef(
        "large_caps",
        "Large Caps",
        "price",
        "XRP",
        "proxy",
        "Proxy: XRP is the only additional large-cap asset this platform tracks beyond "
        "BTC/ETH/SOL — a scope decision, not a broad large-cap index (see NOT_TRACKED).",
    ),
    NodeDef(
        "mid_caps", "Mid Caps", None, None, "unavailable", "No tracked mid-cap asset universe."
    ),
    NodeDef("defi", "DeFi", None, None, "unavailable", "No tracked DeFi-token universe."),
    NodeDef(
        "ai_related",
        "AI-related assets",
        None,
        None,
        "unavailable",
        "No tracked AI-token universe.",
    ),
    NodeDef(
        "meme_assets",
        "Meme assets",
        "retail_meme_trending",
        None,
        "proxy",
        "Retail ATTENTION proxy (trending-mention count across 6 tracked meme coins) — NOT an "
        "observed capital flow; no meme-coin price or flow data is ingested (see NOT_TRACKED).",
    ),
    NodeDef(
        "retail",
        "Retail",
        "retail_small_tx",
        None,
        "proxy",
        "BTC small-transaction count — a retail-activity proxy, never retail-exclusive data.",
    ),
)


@dataclass(frozen=True, slots=True)
class RotationEdge:
    from_node: str
    to_node: str
    status: str  # possible_rotation / no_rotation_signal / unavailable
    evidence_class: str | None  # "inferred" only when status == possible_rotation
    hypothesis: str | None
    from_direction: str | None
    to_direction: str | None


def classify_edge(
    from_node: NodeDef, to_node: NodeDef, dir_from: str | None, dir_to: str | None
) -> RotationEdge:
    fid, tid = from_node.node_id, to_node.node_id
    if dir_from is None or dir_to is None or dir_from == "unavailable" or dir_to == "unavailable":
        return RotationEdge(fid, tid, "unavailable", None, None, dir_from, dir_to)
    if dir_from == "down" and dir_to == "up":
        hyp = (
            f"{from_node.label} decreased while {to_node.label} increased over the same window — "
            "consistent with (but not proof of) capital rotating from the former into the latter. "
            "No transfer between these is directly observed; this is a hypothesis from two "
            "correlated directional readings only."
        )
        return RotationEdge(fid, tid, "possible_rotation", "inferred", hyp, dir_from, dir_to)
    if dir_from == "up" and dir_to == "down":
        hyp = (
            f"{to_node.label} decreased while {from_node.label} increased over the same window — "
            f"consistent with (but not proof of) capital rotating from {to_node.label} into "
            f"{from_node.label} (the reverse direction along this chain). No transfer is directly "
            "observed; this is a hypothesis from two correlated directional readings only."
        )
        return RotationEdge(fid, tid, "possible_rotation", "inferred", hyp, dir_from, dir_to)
    return RotationEdge(fid, tid, "no_rotation_signal", None, None, dir_from, dir_to)


__all__ = ["NODES", "NOT_TRACKED", "NodeDef", "RotationEdge", "classify_edge"]
