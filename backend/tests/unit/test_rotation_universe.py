"""Unit tests for cfi.rotation.universe's node registry (Phase 20): every one of the user's 10
requested categories maps onto at least one node, the EXCLUDED_PAIRS mechanism is internally
consistent, and NOT_TRACKED is populated (never silently narrowed, R3)."""

from __future__ import annotations

from cfi.rotation.universe import (
    EXCLUDED_PAIRS,
    INFORMATIONAL_ONLY,
    LARGE_CAP_ASSETS,
    NODES,
    NODES_BY_ID,
    NOT_TRACKED,
    ROTATION_PARAMETERS_V1,
)

# The Phase 20 instruction's verbatim category list -> the node_id(s) that cover it.
REQUESTED_CATEGORIES = {
    "btc": ("btc",),
    "eth": ("eth",),
    "sol": ("sol",),
    "major assets": ("btc", "eth", "sol", "xrp"),
    "large caps": ("large_caps",),
    "mid caps": ("mid_caps",),
    "defi": ("defi",),
    "ai-related assets": ("ai_related",),
    "meme assets": ("meme_assets",),
    "stablecoins": ("stablecoins_total", "stablecoin_usdt", "stablecoin_usdc"),
}


def test_all_10_requested_categories_are_registered() -> None:
    for category, node_ids in REQUESTED_CATEGORIES.items():
        for node_id in node_ids:
            assert node_id in NODES_BY_ID, f"{category!r} -> missing node {node_id!r}"


def test_node_ids_are_unique() -> None:
    ids = [n.node_id for n in NODES]
    assert len(ids) == len(set(ids))
    assert NODES_BY_ID.keys() == set(ids)


def test_every_node_has_the_fields_required_for_display() -> None:
    for n in NODES:
        assert n.node_id
        assert n.label
        assert n.measurement_class in ("observed", "proxy", "unavailable")
        assert n.scope_note
        # a node with no tracked data at all must be measurement_class 'unavailable' and vice versa
        if n.fetch_key is None:
            assert n.measurement_class == "unavailable"
        else:
            assert n.measurement_class != "unavailable"


_KNOWN_FETCH_KEYS = {
    "asset_share",
    "large_caps_share",
    "stablecoin_growth",
    "stablecoin_share",
    "retail_meme_trending",
}


def test_every_fetch_key_is_a_known_dispatch_key() -> None:
    for n in NODES:
        if n.fetch_key is not None:
            assert n.fetch_key in _KNOWN_FETCH_KEYS, f"{n.node_id} -> unknown key {n.fetch_key!r}"


def test_large_caps_is_exactly_the_four_tracked_assets() -> None:
    assert set(LARGE_CAP_ASSETS) == {"BTC", "ETH", "SOL", "XRP"}


def test_excluded_pairs_cover_large_caps_and_stablecoin_aggregates_both_directions() -> None:
    for asset in LARGE_CAP_ASSETS:
        assert ("large_caps", asset.lower()) in EXCLUDED_PAIRS
        assert (asset.lower(), "large_caps") in EXCLUDED_PAIRS
    for node_id in ("stablecoin_usdt", "stablecoin_usdc"):
        assert ("stablecoins_total", node_id) in EXCLUDED_PAIRS
        assert (node_id, "stablecoins_total") in EXCLUDED_PAIRS


def test_excluded_pairs_reference_real_node_ids() -> None:
    for a, b in EXCLUDED_PAIRS:
        assert a in NODES_BY_ID, f"unknown node {a!r} in EXCLUDED_PAIRS"
        assert b in NODES_BY_ID, f"unknown node {b!r} in EXCLUDED_PAIRS"


def test_meme_assets_is_the_only_informational_only_node() -> None:
    assert frozenset({"meme_assets"}) == INFORMATIONAL_ONLY
    assert NODES_BY_ID["meme_assets"].fetch_key == "retail_meme_trending"


def test_not_tracked_is_a_non_empty_tuple_of_strings() -> None:
    assert isinstance(NOT_TRACKED, tuple)
    assert len(NOT_TRACKED) > 0
    assert all(isinstance(s, str) and s for s in NOT_TRACKED)


def test_parameters_are_versioned() -> None:
    assert ROTATION_PARAMETERS_V1.version
    assert ROTATION_PARAMETERS_V1.description
