"""Unit tests for cfi.divergence.comparisons: quadrant labeling, the standardized matrix, the
divergent/aligned classification, and the registry of the 10 comparisons named in Phase 13."""

from __future__ import annotations

from cfi.divergence.comparisons import COMPARISONS, is_divergent, quadrant_label, standard_matrix


def test_quadrant_label_uses_arrows() -> None:
    assert quadrant_label("Institutional", "Retail", "up", "up") == "Institutional ↑ / Retail ↑"
    assert quadrant_label("Institutional", "Retail", "up", "down") == "Institutional ↑ / Retail ↓"
    assert quadrant_label("Institutional", "Retail", "down", "up") == "Institutional ↓ / Retail ↑"
    assert quadrant_label("Institutional", "Retail", "down", "down") == "Institutional ↓ / Retail ↓"


def test_standard_matrix_has_exactly_the_four_named_cells() -> None:
    cells = standard_matrix("Institutional", "Retail")
    assert cells == [
        "Institutional ↑ / Retail ↑",
        "Institutional ↑ / Retail ↓",
        "Institutional ↓ / Retail ↑",
        "Institutional ↓ / Retail ↓",
    ]


def test_whale_vs_retail_matrix_includes_the_two_requested_cross_cells() -> None:
    cells = standard_matrix("Whale", "Retail")
    assert "Whale ↑ / Retail ↓" in cells
    assert "Whale ↓ / Retail ↑" in cells


def test_is_divergent_only_true_for_opposite_up_down() -> None:
    assert is_divergent("up", "down") is True
    assert is_divergent("down", "up") is True
    assert is_divergent("up", "up") is False
    assert is_divergent("down", "down") is False
    assert is_divergent("flat", "up") is False
    assert is_divergent("unavailable", "up") is False


def test_registry_has_all_ten_numbered_comparisons() -> None:
    assert len(COMPARISONS) == 10
    assert {c.number for c in COMPARISONS.values()} == set(range(1, 11))
    by_number = {c.number: c.comparison_id for c in COMPARISONS.values()}
    assert by_number[3] == "whale_vs_retail"
    assert by_number[10] == "macro_vs_market_structure"


def test_every_comparison_declares_a_valid_asset_scope() -> None:
    for c in COMPARISONS.values():
        assert c.asset_scope in ("none", "shared", "leg_a_only", "leg_b_only")
        if c.asset_scope == "none":
            assert c.allowed_assets is None
        else:
            assert c.allowed_assets  # non-empty
