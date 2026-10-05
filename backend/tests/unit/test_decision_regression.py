"""Regression fixtures A-J for the L4.5 engine (each fixture is a *sequence* of snapshots with
executed assertions), as approved in the Phase 38.1 methodology. The orderings below are written
out independently of ``cfi.decision``: stance strength (ordering (a)) and posture permissiveness
(ordering (b), decision D-O)."""

# ruff: noqa: PT018
from __future__ import annotations

import itertools
from itertools import combinations
from typing import Any

from cfi.decision import AssessmentResult, Confidence, Posture, RiskLevel, Stance, assess
from tests.decision_builders import ELEVATED_ACTIVITY, STRONG_LONG, make_payload

STRENGTH = {
    "Strongly Bullish": 3,
    "Bullish": 2,
    "Cautiously Bullish": 1,
    "Neutral / Wait": 0,
    "Cautiously Bearish": 1,
    "Bearish": 2,
    "Strongly Bearish": 3,
}
PERMISSIVE = {
    "MONITOR CONSTRUCTIVE CONDITIONS": 5,
    "MONITOR WITH ELEVATED CAUTION": 4,
    "AVOID ADDING HIGH-RISK EXPOSURE": 3,
    "WAIT FOR CONFIRMATION": 2,
    "REASSESS / REDUCE RISK": 1,
}
CONF = {"Insufficient Evidence": 0, "Low": 1, "Moderate": 2, "High": 3}
BULLISH = {"Strongly Bullish", "Bullish", "Cautiously Bullish"}
LEVELS = {"Low": 0, "Moderate": 1, "Elevated": 2, "High": 3}


def run(codes: list[str], **ctx: Any) -> AssessmentResult:
    return assess(make_payload(codes, **ctx), "BTC")


def risks(r: AssessmentResult) -> tuple[str, ...]:
    return tuple(x.level.value for x in r.risks)


def strength(r: AssessmentResult) -> int:
    return STRENGTH.get(r.final_stance.value, 0)


def perm(r: AssessmentResult) -> int | None:
    return PERMISSIVE.get(r.posture.value)


def _no_loosening(before: AssessmentResult, after: AssessmentResult) -> None:
    assert strength(after) <= strength(before)
    pb, pa = perm(before), perm(after)
    if pb is not None and pa is not None:
        assert pa <= pb
    if before.final_stance in BULLISH or after.final_stance in BULLISH:
        assert after.final_stance.value not in {s for s in STRENGTH if "Bearish" in s}


# ------------------------------------------------------------------------------------- A
def _ladder(
    base: list[str], expected: list[tuple[str, str, str]], missing: list[tuple[str, ...]]
) -> None:
    results = [
        run(base[:], **{}),
        run([*base[:4], "U"]),
        run([*base[:3], "U", "U"]),
    ]
    for r, (stance, conf, posture), miss in zip(results, expected, missing, strict=True):
        assert (r.final_stance.value, r.confidence.value, r.posture.value) == (
            stance,
            conf,
            posture,
        )
        assert r.missing == miss
    for before, after in itertools.pairwise(results):
        assert strength(after) <= strength(before)  # stance strength never increases
        assert (after.final_stance in BULLISH) == (before.final_stance in BULLISH) or strength(
            after
        ) == 0
        assert after.tally.n < before.tally.n  # coverage strictly decreases
        assert after.tally.n_neutral < before.tally.n_neutral or before.tally.n_neutral == 0
        assert CONF[after.confidence.value] <= CONF[before.confidence.value]
        assert after.tally.s == before.tally.s and after.tally.a == before.tally.a


def test_fixture_a1_neutral_disappearance_never_strengthens_stance() -> None:
    _ladder(
        ["S1", "S1", "A1", "N", "N"],
        [
            ("Neutral / Wait", "High", "WAIT FOR CONFIRMATION"),
            ("Neutral / Wait", "Moderate", "WAIT FOR CONFIRMATION"),
            ("Neutral / Wait", "Low", "WAIT FOR CONFIRMATION"),
        ],
        [(), ("market_structure",), ("macro", "market_structure")],
    )


def test_fixture_a2_neutral_disappearance_never_strengthens_stance() -> None:
    _ladder(
        ["S1", "S1", "S1", "N", "N"],
        [
            ("Bullish", "High", "MONITOR CONSTRUCTIVE CONDITIONS"),
            ("Bullish", "Moderate", "MONITOR WITH ELEVATED CAUTION"),
            ("Bullish", "Low", "MONITOR WITH ELEVATED CAUTION"),
        ],
        [(), ("market_structure",), ("macro", "market_structure")],
    )


def test_fixture_a_unavailable_is_not_counted_as_neutral() -> None:
    r = run(["S1", "S1", "A1", "U", "U"])
    assert (r.tally.n_neutral, r.tally.u) == (0, 2)
    assert r.tally.d == 5 and r.tally.n == 3


# ------------------------------------------------------------------------------------- B
def test_fixture_b_regime_disappearance_cu01() -> None:
    cases = [(["S1", "S1", "S1", "N", "S1"], "Bullish"), (["S2"] * 5, "Strongly Bullish")]
    for codes, raw in cases:
        with_regime = run(codes)
        without = run(codes, regime=None)
        assert with_regime.final_stance.value == raw
        # tally and raw directional stance are identical with and without regime (INV-5)
        assert with_regime.tally == without.tally
        assert (
            without.directional_stance_before_limits == with_regime.directional_stance_before_limits
        )
        # final stance never stronger; CU-01 holds it at Neutral / Wait
        assert without.final_stance is Stance.NEUTRAL
        assert without.posture is Posture.WAIT_FOR_CONFIRMATION
        # no Insufficient Evidence solely because regime is missing; regime is missing *context*
        assert without.final_stance.value != "Insufficient Evidence"
        assert without.missing_context == ("regime",)
        assert "regime" not in without.missing
        # confidence drops by exactly one level (CN-05)
        assert CONF[without.confidence.value] == CONF[with_regime.confidence.value] - 1
        ids = without.explanation.all_template_ids()
        assert "CTX.regime.missing" in ids and "CAPU.regime" in ids
        _no_loosening(with_regime, without)
        assert "Bearish" not in without.final_stance.value  # no bearish stance created


# ------------------------------------------------------------------------------------- C
def test_fixture_c_strong_conflict_is_never_averaged_away() -> None:
    steps = [
        ["S2", "N", "N", "N", "A2"],  # one strong on each side
        ["S1", "S1", "A1", "A1", "N"],  # two plain on each side
        ["S2", "U", "N", "N", "A2"],  # strong conflict with a missing domain
    ]
    for codes in steps:
        r = run(codes)
        assert r.conflict is True
        assert r.final_stance is Stance.NEUTRAL
        assert r.posture is Posture.WAIT_FOR_CONFIRMATION
        assert "CONFLICT.phrase" in r.explanation.directional
        assert "CN-02" in r.confidence_rule_ids
        assert r.supportive and r.adverse  # both sides are listed, not netted away


# ------------------------------------------------------------------------------------- D
def test_fixture_d_constructive_evidence_with_rising_risk() -> None:
    codes = ["S2"] * 5
    ladder: list[dict[str, Any]] = [
        {},
        {"derivatives": "moderate stress"},
        {"derivatives": "elevated stress"},
        {"derivatives": "high stress"},
        {"derivatives": "high stress", "volatility": "extreme_high", "extreme_other": True},
        {
            "derivatives": "high stress",
            "volatility": "extreme_high",
            "extreme_other": True,
            "regime": "capitulation",
        },
    ]
    results = [run(codes, **c) for c in ladder]
    expected = [
        ("Strongly Bullish", "MONITOR CONSTRUCTIVE CONDITIONS"),
        ("Strongly Bullish", "MONITOR CONSTRUCTIVE CONDITIONS"),
        ("Strongly Bullish", "MONITOR WITH ELEVATED CAUTION"),
        ("Cautiously Bullish", "AVOID ADDING HIGH-RISK EXPOSURE"),
        ("Cautiously Bullish", "AVOID ADDING HIGH-RISK EXPOSURE"),
        ("Neutral / Wait", "WAIT FOR CONFIRMATION"),
    ]
    for r, (stance, posture) in zip(results, expected, strict=True):
        assert (r.final_stance.value, r.posture.value) == (stance, posture)
        assert r.tally == results[0].tally  # directional tally identical on every step
        assert "Bearish" not in r.final_stance.value  # risk never creates a bearish stance
    for before, after in itertools.pairwise(results):
        assert max(LEVELS[x] for x in risks(after) if x in LEVELS) >= max(
            LEVELS[x] for x in risks(before) if x in LEVELS
        )
        _no_loosening(before, after)


# ------------------------------------------------------------------------------------- E
def test_fixture_e_insufficient_directional_coverage() -> None:
    below = [
        run(["S2", "S2", "U", "U", "U"]),
        run(["N", "N", "U", "U", "U"]),
        assess(make_payload(["S1", "U", "U", "U"], scope="SOL"), "SOL"),
    ]
    for r in below:
        assert r.final_stance is Stance.INSUFFICIENT
        assert r.confidence is Confidence.INSUFFICIENT
        assert r.posture is Posture.INVESTIGATE_FURTHER
        assert "STANCE.Insufficient Evidence" in r.explanation.directional  # "Insufficient data."
        assert r.missing  # missing evidence listed explicitly
        assert r.conflict is False
    assert run(["S1", "S1", "S1", "U", "U"]).final_stance is Stance.BULLISH  # 3 of 5 classifies
    two_of_four = assess(make_payload(["S1", "S1", "U", "U"], scope="SOL"), "SOL")
    assert two_of_four.final_stance is Stance.CAUTIOUSLY_BULLISH  # exactly 50%: allowed
    assert (
        run(["N", "N", "U", "U", "U"]).final_stance is Stance.INSUFFICIENT
    )  # neutral alone is not enough


# ------------------------------------------------------------------------------------- F
def test_fixture_f_regime_disappears_in_every_case() -> None:
    pairs = [
        ({"regime": "euphoria"}, "Cautiously Bullish"),  # F.1 RC-03 cap
        ({"regime": "distribution"}, "Neutral / Wait"),  # F.2 RC-04
        ({"regime": "recovery"}, "Bullish"),  # F.3 evaluated and does not apply
    ]
    codes = ["S1"] * 5
    for ctx, expected in pairs:
        with_regime = run(codes, **ctx)
        without = run(codes, regime=None)
        assert with_regime.final_stance.value == expected
        assert without.final_stance is Stance.NEUTRAL  # Case B differs from Case A
        assert without.posture is Posture.WAIT_FOR_CONFIRMATION
        assert with_regime.tally == without.tally
        _no_loosening(with_regime, without)
        assert "CAPU.regime" in without.explanation.all_template_ids()
        assert without.final_stance.value != "Insufficient Evidence"


# ------------------------------------------------------------------------------------- G
def test_fixture_g_derivatives_safety_input_disappears() -> None:
    codes = ["S2"] * 5
    high = run(codes, derivatives="high stress")
    missing = run(codes, derivatives=None)
    low = run(codes, derivatives="low stress")
    for observed in (high, low):
        _no_loosening(observed, missing)
    assert (missing.final_stance, missing.posture) == (
        Stance.CAUTIOUSLY_BULLISH,
        Posture.AVOID_ADDING_HIGH_RISK,
    )
    assert low.final_stance is Stance.STRONGLY_BULLISH  # removal from "not applicable" tightens
    assert missing.tally == low.tally
    leverage = next(r for r in missing.risks if r.dimension.value == "leverage")
    assert leverage.level is RiskLevel.NOT_ASSESSED  # never Low
    assert "CAPU.derivatives" in missing.explanation.all_template_ids()
    # freshness: not_assessed (v0) never triggers CU-02, CN-03 or a stale floor
    not_assessed = run(codes, derivatives="low stress")
    fresh = run(codes, derivatives="low stress", derivatives_freshness="fresh")
    stale = run(codes, derivatives="low stress", derivatives_freshness="stale")
    assert not any(c.rule_id == "CU-02" for c in not_assessed.cap_u)
    assert "CN-03" not in not_assessed.confidence_rule_ids
    assert not_assessed.final_stance == fresh.final_stance == Stance.STRONGLY_BULLISH
    assert not_assessed.confidence == fresh.confidence == Confidence.HIGH
    assert "LIMIT.derivatives_freshness" in not_assessed.limitations
    assert "LIMIT.derivatives_freshness" not in fresh.limitations
    assert stale.confidence is Confidence.MODERATE and "CN-03" in stale.confidence_rule_ids
    assert stale.posture is Posture.MONITOR_ELEVATED_CAUTION
    assert risks(stale) == ("Low", "Low", "Moderate", "Low", "Low", "Moderate")


# ------------------------------------------------------------------------------------- H
def test_fixture_h_anomaly_safety_input_disappears() -> None:
    codes = ["S2"] * 5
    critical = run(codes, volatility="extreme_high", extreme_other=True)
    clean = run(codes)
    missing = run(codes, volatility=None)
    assert critical.final_stance is Stance.CAUTIOUSLY_BULLISH
    assert clean.final_stance is Stance.STRONGLY_BULLISH
    for observed in (critical, clean):
        _no_loosening(observed, missing)
    assert (missing.final_stance, missing.posture) == (
        Stance.CAUTIOUSLY_BULLISH,
        Posture.AVOID_ADDING_HIGH_RISK,
    )
    vol = next(r for r in missing.risks if r.dimension.value == "volatility")
    assert vol.level is RiskLevel.NOT_ASSESSED
    assert "CAPU.anomaly" in missing.explanation.all_template_ids()
    assert missing.missing_context == ("volatility_anomaly",)
    assert missing.tally == clean.tally


# ------------------------------------------------------------------------------------- I
def test_fixture_i_multiple_cap_sources_disappear() -> None:
    codes = ["S2"] * 5
    sources = ("regime", "derivatives", "volatility")

    def with_missing(subset: tuple[str, ...]) -> AssessmentResult:
        return run(codes, **dict.fromkeys(subset))

    subsets = [c for n in range(4) for c in combinations(sources, n)]
    results = {s: with_missing(s) for s in subsets}
    assert len(results) == 8
    for a in subsets:
        for b in subsets:
            if set(a) <= set(b):
                _no_loosening(results[a], results[b])
    for subset, r in results.items():
        assert r.tally == results[()].tally
        assert "Bearish" not in r.final_stance.value
        if "regime" in subset:
            assert (r.final_stance, r.posture) == (Stance.NEUTRAL, Posture.WAIT_FOR_CONFIRMATION)
        elif subset:
            assert (r.final_stance, r.posture) == (
                Stance.CAUTIOUSLY_BULLISH,
                Posture.AVOID_ADDING_HIGH_RISK,
            )
        else:
            assert r.final_stance is Stance.STRONGLY_BULLISH
        # every missing source is disclosed
        names = {
            "regime": "regime",
            "derivatives": "derivatives",
            "volatility": "volatility_anomaly",
        }
        assert set(r.missing_context) == {names[s] for s in subset}


# ------------------------------------------------------------------------------------- J
def test_fixture_j_authoritative_cap_u_table() -> None:
    codes = ["S2"] * 5
    rows: list[tuple[dict[str, Any], str, str, tuple[str, ...]]] = [
        ({"regime": None}, "Neutral / Wait", "WAIT FOR CONFIRMATION", ("CU-01",)),
        (
            {"derivatives": None},
            "Cautiously Bullish",
            "AVOID ADDING HIGH-RISK EXPOSURE",
            ("CU-02",),
        ),
        ({"volatility": None}, "Cautiously Bullish", "AVOID ADDING HIGH-RISK EXPOSURE", ("CU-03",)),
        (
            {"derivatives": None, "volatility": None},
            "Cautiously Bullish",
            "AVOID ADDING HIGH-RISK EXPOSURE",
            ("CU-02", "CU-03"),
        ),
        (
            {"regime": None, "derivatives": None},
            "Neutral / Wait",
            "WAIT FOR CONFIRMATION",
            ("CU-01", "CU-02"),
        ),
        (
            {"regime": None, "derivatives": None, "volatility": None},
            "Neutral / Wait",
            "WAIT FOR CONFIRMATION",
            ("CU-01", "CU-02", "CU-03"),
        ),
    ]
    base = run(codes)
    for ctx, stance, posture, rules in rows:
        r = run(codes, **ctx)
        assert (r.final_stance.value, r.posture.value) == (stance, posture)
        assert tuple(c.rule_id for c in r.cap_u) == rules
        assert r.directional_stance_before_limits is Stance.STRONGLY_BULLISH  # raw preserved
        assert r.tally == base.tally  # no directional vote
        for rec in r.cap_u:  # complete traceability record
            assert rec.source_status == "not_evaluable"
            assert rec.reason_id == f"{rec.rule_id}:{rec.cap_source}=not_evaluable"
            assert rec.directional_stance_before_limits is Stance.STRONGLY_BULLISH
            assert rec.final_stance is r.final_stance and rec.final_posture is r.posture
            assert rec.applied_ceiling is r.final_stance
            assert (rec.methodology_version, rec.parameter_version) == (
                "decision_methodology.v0",
                "decision_params.v0",
            )
            assert rec.source_field_id
    # no missing source is a neutral reading or an assumed risk value
    j6 = run(codes, regime=None, derivatives=None, volatility=None)
    by_dim = {x.dimension.value: x.level for x in j6.risks}
    assert by_dim["leverage"] is by_dim["volatility"] is RiskLevel.NOT_ASSESSED
    # CAP-U applies to bullish-family raw stances only
    bearish = run(["A2"] * 5, regime=None, derivatives=None, volatility=None)
    assert bearish.final_stance is Stance.STRONGLY_BEARISH and not bearish.cap_u


def test_elevated_activity_and_speculation_are_posture_level_only() -> None:
    hot = run(["S1"] * 5, activity=ELEVATED_ACTIVITY, speculation=STRONG_LONG)
    calm = run(["S1"] * 5)
    assert hot.final_stance is calm.final_stance is Stance.BULLISH  # risk never changes the stance
    assert hot.posture is Posture.AVOID_ADDING_HIGH_RISK
