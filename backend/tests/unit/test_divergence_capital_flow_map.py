"""Unit tests for cfi.divergence.capital_flow_map: the 12-node chain and the pure edge
classification between OBSERVED FLOW and INFERRED ROTATION."""

from __future__ import annotations

from cfi.divergence.capital_flow_map import NODES, classify_edge


def test_node_order_matches_the_phase_13_chain() -> None:
    assert [n.node_id for n in NODES] == [
        "institutions",
        "whales",
        "liquidity",
        "btc",
        "eth",
        "sol",
        "large_caps",
        "mid_caps",
        "defi",
        "ai_related",
        "meme_assets",
        "retail",
    ]


def test_untracked_categories_have_no_fetch_key() -> None:
    untracked = {"mid_caps", "defi", "ai_related"}
    for node in NODES:
        if node.node_id in untracked:
            assert node.fetch_key is None
            assert node.measurement_class == "unavailable"
        else:
            assert node.fetch_key is not None


def test_meme_assets_node_is_a_proxy_not_observed() -> None:
    meme = next(n for n in NODES if n.node_id == "meme_assets")
    assert meme.measurement_class == "proxy"
    assert "NOT an observed capital flow" in meme.scope_note


def test_classify_edge_down_up_is_a_hedged_possible_rotation() -> None:
    a, b = NODES[0], NODES[1]
    edge = classify_edge(a, b, "down", "up")
    assert edge.status == "possible_rotation"
    assert edge.evidence_class == "inferred"
    assert edge.hypothesis is not None
    assert "consistent with (but not proof of)" in edge.hypothesis
    assert "No transfer" in edge.hypothesis


def test_classify_edge_same_direction_is_no_rotation_signal() -> None:
    a, b = NODES[0], NODES[1]
    edge = classify_edge(a, b, "up", "up")
    assert edge.status == "no_rotation_signal"
    assert edge.evidence_class is None
    assert edge.hypothesis is None

    edge2 = classify_edge(a, b, "down", "down")
    assert edge2.status == "no_rotation_signal"


def test_classify_edge_unavailable_when_either_direction_unknown() -> None:
    a, b = NODES[0], NODES[1]
    assert classify_edge(a, b, None, "up").status == "unavailable"
    assert classify_edge(a, b, "unavailable", "up").status == "unavailable"
    assert classify_edge(a, b, "up", None).status == "unavailable"


def test_classify_edge_never_claims_money_moved() -> None:
    """R1/R3: the hypothesis text must hedge, never assert an observed transfer."""
    a, b = NODES[0], NODES[1]
    for combo in (("down", "up"), ("up", "down")):
        edge = classify_edge(a, b, *combo)
        assert edge.hypothesis is not None
        assert "consistent with" in edge.hypothesis
        assert "directly observed" in edge.hypothesis
