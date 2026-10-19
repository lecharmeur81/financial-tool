"""Phase 54 step 1: the pure portfolio exposure calculation over SIMULATED paper trades.

Database-free. Covers empty / single / multiple assets, long-short conventions, share denominators,
concentration, leverage and margin validation, missing prices, brief relations (including missing
and unusable briefs), determinism and input immutability, and the response's boundary language."""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

import pytest

from cfi.analyst.universe import BANNED_PATTERNS
from cfi.portfolio import NOT_CLAIMED, UNAVAILABLE, build_exposure, summarize_brief
from cfi.portfolio.exposure import _relation

ASSETS = ("BTC", "ETH", "SOL", "XRP")


def pos(
    tid: str,
    asset: str = "BTC",
    direction: str = "long",
    notional: str = "1000",
    leverage: str = "1",
    margin: str | None = None,
    price: str = "ok",
) -> dict[str, Any]:
    n, lev = Decimal(notional), Decimal(leverage)
    return {
        "trade_id": tid,
        "asset": asset,
        "direction": direction,
        "notional": n,
        "leverage": lev,
        "margin": Decimal(margin) if margin is not None else n / lev,
        "price_status": price,
    }


def assessed(stance: str, state: str = "candidate_unresolved") -> dict[str, Any]:
    return {
        "status": "assessed",
        "stance": stance,
        "confidence": "Moderate",
        "posture": "MONITOR WITH ELEVATED CAUTION",
        "decision_state": state,
        "snapshot_as_of": "2026-10-19T08:00:00Z",
        "snapshot_row_id": 7,
    }


def run(positions: list[dict[str, Any]], briefs: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_exposure(positions, briefs or {}, ASSETS)


# ------------------------------------------------------------------ empty and degenerate


def test_an_empty_portfolio_has_no_ratios_and_says_so() -> None:
    out = run([])
    s = out["summary"]
    assert s["status"] == "empty"
    assert (s["gross_notional"], s["net_notional"], s["total_margin"]) == ("0", "0", "0")
    for key in ("notional_weighted_leverage", "largest_asset", "largest_asset_share"):
        assert s[key] is None  # zero denominator: undefined, not zero
    assert s["concentration_hhi"] is None
    assert out["assets"] == []
    assert out["positions"] == []
    assert out["data_quality"]["has_gaps"] is False


def test_only_invalid_positions_give_no_valid_portfolio() -> None:
    out = run([pos("a", notional="0"), pos("b", direction="sideways")])
    assert out["summary"]["status"] == "no_valid_positions"
    assert out["summary"]["largest_asset_share"] is None
    assert [p["trade_id"] for p in out["invalid_positions"]] == ["a", "b"]
    assert out["data_quality"]["has_gaps"] is True


# ------------------------------------------------------------------ conventions and shares


def test_a_single_long_asset_is_fully_concentrated() -> None:
    out = run([pos("a", notional="2500", leverage="5")])
    s = out["summary"]
    assert s["status"] == "computed"
    assert (s["gross_notional"], s["long_notional"], s["short_notional"]) == ("2500", "2500", "0")
    assert s["net_notional"] == "2500"
    assert s["total_margin"] == "500"
    assert s["largest_asset"] == "BTC"
    assert Decimal(s["largest_asset_share"]) == 1
    assert Decimal(s["concentration_hhi"]) == 1


def test_long_is_positive_short_is_negative_and_gross_ignores_sign() -> None:
    out = run([pos("a", notional="1000"), pos("b", direction="short", notional="400")])
    s = out["summary"]
    assert (s["gross_notional"], s["net_notional"]) == ("1400", "600")
    assert (s["long_notional"], s["short_notional"]) == ("1000", "400")
    btc = out["assets"][0]
    assert (btc["gross_notional"], btc["net_notional"], btc["net_direction"]) == (
        "1400",
        "600",
        "long",
    )
    assert btc["position_count"] == 2


def test_shares_use_gross_notional_and_sum_to_one() -> None:
    out = run(
        [
            pos("a", "BTC", notional="600"),
            pos("b", "ETH", direction="short", notional="300"),
            pos("c", "SOL", notional="100"),
        ]
    )
    shares = {a["asset"]: Decimal(a["share_of_gross"]) for a in out["assets"]}
    assert shares == {"BTC": Decimal("0.6"), "ETH": Decimal("0.3"), "SOL": Decimal("0.1")}
    assert sum(shares.values()) == 1
    assert [a["asset"] for a in out["assets"]] == ["BTC", "ETH", "SOL"]  # gross descending


def test_concentration_measures() -> None:
    out = run(
        [
            pos("a", "BTC", notional="500"),
            pos("b", "ETH", notional="300"),
            pos("c", "SOL", notional="200"),
        ]
    )
    s = out["summary"]
    assert s["largest_asset"] == "BTC"
    assert Decimal(s["largest_asset_share"]) == Decimal("0.5")
    assert Decimal(s["concentration_hhi"]) == Decimal("0.25") + Decimal("0.09") + Decimal("0.04")
    equal = run([pos(str(i), a, notional="100") for i, a in enumerate(ASSETS)])
    assert Decimal(equal["summary"]["concentration_hhi"]) == Decimal("0.25")  # 1/n for n equal


def test_a_perfect_hedge_has_zero_net_and_no_net_direction() -> None:
    out = run(
        [pos("a", notional="500"), pos("b", direction="short", notional="500")],
        {"BTC": assessed("Bullish")},
    )
    s = out["summary"]
    assert s["net_notional"] == "0"
    assert s["gross_notional"] == "1000"
    assert out["assets"][0]["net_direction"] == "none"
    assert out["assets"][0]["brief_relation"] == "no_net_direction"
    assert out["assets"][0]["disagreement"] is None


def test_notional_weighted_leverage_and_total_margin() -> None:
    out = run(
        [pos("a", notional="1000", leverage="2"), pos("b", "ETH", notional="3000", leverage="10")]
    )
    s = out["summary"]
    assert Decimal(s["notional_weighted_leverage"]) == Decimal("8")  # (2000 + 30000) / 4000
    assert Decimal(s["total_margin"]) == Decimal("500") + Decimal("300")


# ------------------------------------------------------------------ invalid data


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"asset": "DOGE"}, "unknown_asset"),
        ({"direction": "flat"}, "unknown_direction"),
        ({"notional": Decimal(0)}, "invalid_notional"),
        ({"notional": Decimal(-5)}, "invalid_notional"),
        ({"notional": Decimal("NaN")}, "invalid_notional"),
        ({"notional": None}, "invalid_notional"),
        ({"leverage": Decimal(0)}, "invalid_leverage"),
        ({"leverage": Decimal(-2)}, "invalid_leverage"),
        ({"margin": None}, "invalid_margin"),
        ({"margin": Decimal(-1)}, "invalid_margin"),
        (
            {"margin": Decimal(999), "leverage": Decimal(2)},
            "margin_inconsistent_with_notional_and_leverage",
        ),
    ],
)
def test_unusable_positions_are_excluded_with_a_reason_and_never_repaired(
    changes: dict[str, Any], reason: str
) -> None:
    bad = {**pos("bad"), **changes}
    out = run([pos("ok", "ETH", notional="100"), bad])
    assert out["summary"]["gross_notional"] == "100"  # the bad one counts nowhere
    assert out["summary"]["asset_count"] == 1
    assert out["invalid_positions"] == [{"trade_id": "bad", "reasons": [reason]}]
    assert out["source"]["positions_received"] == 2
    assert out["source"]["positions_valid"] == 1


def test_a_malformed_position_does_not_crash() -> None:
    out = run([{"trade_id": "x"}])
    assert out["invalid_positions"][0]["trade_id"] == "x"
    assert "unknown_asset" in out["invalid_positions"][0]["reasons"]


# ------------------------------------------------------------------ prices


def test_a_missing_price_flags_the_position_without_changing_the_notional_metrics() -> None:
    with_price = run([pos("a", notional="700")])
    without = run([pos("a", notional="700", price="missing")])
    assert without["summary"] == with_price["summary"]
    assert without["positions"][0]["price_status"] == "missing"
    assert without["data_quality"]["positions_missing_price"] == 1
    assert without["data_quality"]["has_gaps"] is True


# ------------------------------------------------------------------ brief relations


@pytest.mark.parametrize(
    ("direction", "stance", "relation", "disagreement"),
    [
        ("long", "Strongly Bullish", "same_direction", False),
        ("long", "Bullish", "same_direction", False),
        ("long", "Cautiously Bullish", "same_direction", False),
        ("long", "Cautiously Bearish", "opposite_direction", True),
        ("long", "Strongly Bearish", "opposite_direction", True),
        ("short", "Bearish", "same_direction", False),
        ("short", "Bullish", "opposite_direction", True),
        ("long", "Neutral / Wait", "stance_neutral", None),
        ("short", "Neutral / Wait", "stance_neutral", None),
        ("long", "Insufficient Evidence", "no_directional_view", None),
        ("short", "Insufficient Evidence", "no_directional_view", None),
        ("long", "Some New Stance", "not_assessed", None),
    ],
)
def test_brief_relation_semantics(
    direction: str, stance: str, relation: str, disagreement: bool | None
) -> None:
    out = run([pos("a", direction=direction)], {"BTC": assessed(stance)})
    p = out["positions"][0]
    assert (p["brief_relation"], p["disagreement"]) == (relation, disagreement)
    a = out["assets"][0]
    assert (a["brief_relation"], a["disagreement"]) == (relation, disagreement)


def test_a_missing_or_unusable_brief_is_not_assessed_never_neutral() -> None:
    cases: list[dict[str, Any]] = [
        {},  # no entry
        {"BTC": None},
        {"BTC": {"status": "not_assessed", "reason": "No stored snapshot exists yet."}},
        {"BTC": {"status": "assessed", "stance": ""}},
        {"BTC": {"status": "assessed"}},
    ]
    for briefs in cases:
        out = run([pos("a")], briefs)
        a = out["assets"][0]
        assert a["brief"]["status"] == "not_assessed"
        assert a["brief_relation"] == "not_assessed"
        assert a["disagreement"] is None
        assert out["data_quality"]["assets_without_assessed_brief"] == ["BTC"]
        assert out["data_quality"]["has_gaps"] is True
    reason = run([pos("a")], cases[2])["assets"][0]["brief"]["reason"]
    assert reason == "No stored snapshot exists yet."


def test_the_brief_fields_are_copied_verbatim() -> None:
    out = run([pos("a")], {"BTC": assessed("Bullish", "insufficient_evidence")})
    b = out["assets"][0]["brief"]
    assert (b["stance"], b["confidence"], b["decision_state"]) == (
        "Bullish",
        "Moderate",
        "insufficient_evidence",
    )
    assert b["snapshot_row_id"] == 7


def test_relation_helper_handles_a_zero_sign() -> None:
    assert _relation(0, assessed("Bullish")) == ("no_net_direction", None)
    assert _relation(0, {"status": "not_assessed", "reason": "x"}) == ("not_assessed", None)


def test_summarize_brief_copies_the_contract_fields() -> None:
    brief = {
        "assessment": {
            "stance": {"final": "Bearish", "confidence": "Low", "posture": "WAIT"},
            "investment_state": {"decision_state": "contradicted_evidence"},
        },
        "snapshot": {"as_of": "t", "row_id": 3},
    }
    s = summarize_brief(brief)
    assert s == {
        "status": "assessed",
        "stance": "Bearish",
        "confidence": "Low",
        "posture": "WAIT",
        "decision_state": "contradicted_evidence",
        "snapshot_as_of": "t",
        "snapshot_row_id": 3,
    }


# ------------------------------------------------------------------ determinism, boundaries


def test_inputs_are_not_mutated_and_the_output_is_deterministic_and_order_independent() -> None:
    positions = [
        pos("b", "ETH", notional="300"),
        pos("a", "BTC", notional="700"),
        pos("c", "BTC", "short", "100"),
    ]
    briefs = {"BTC": assessed("Bullish"), "ETH": assessed("Bearish")}
    before = (copy.deepcopy(positions), copy.deepcopy(briefs))
    first = build_exposure(positions, briefs, ASSETS)
    second = build_exposure(list(reversed(positions)), briefs, ASSETS)
    assert (positions, briefs) == before
    assert first == second


def test_every_response_is_labelled_simulated_and_lists_what_is_unavailable() -> None:
    for out in (run([]), run([pos("a")])):
        assert out["contract_version"] == "portfolio_exposure.v0"
        assert out["source"]["kind"] == "simulated_paper_trades"
        assert "Not real holdings" in out["source"]["label"]
        assert [u["id"] for u in out["unavailable"]] == [u["id"] for u in UNAVAILABLE]
        assert {u["id"] for u in out["unavailable"]} == {
            "PF-UNV-HOLDINGS",
            "PF-UNV-SECTOR",
            "PF-UNV-CORRELATION",
            "PF-UNV-LIQUIDITY",
            "PF-UNV-VERDICT",
        }
        assert out["not_claimed"] == [dict(n) for n in NOT_CLAIMED]
        assert {n["id"] for n in out["not_claimed"]} >= {"PF-NOT-REAL-HOLDINGS", "PF-NOT-ADVICE"}


def test_no_unsupported_claim_language_in_any_fixed_text() -> None:
    texts = [n["text"] for n in NOT_CLAIMED] + [u["reason"] for u in UNAVAILABLE]
    out = run([pos("a")], {"BTC": assessed("Bullish")})
    texts += out["conventions"]
    for text in texts:
        for name, pattern in BANNED_PATTERNS.items():
            assert not pattern.search(text), (name, text)
