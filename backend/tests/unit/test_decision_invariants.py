"""Invariant and property tests for the L4.5 engine (INV-1 .. INV-11, methodology section 14).

Method (no Hypothesis, no new dependency): exhaustive deterministic enumeration where practical
(6^5 reading combinations x context states), pytest parameterisation, and seeded
``random.Random`` generators for the broader state space. Everything is reproducible.
"""

# ruff: noqa: PT018
from __future__ import annotations

import copy
import itertools
import random
import re
from typing import Any

import pytest

from cfi.decision import AssessmentResult, Confidence, Posture, RiskLevel, Stance, assess
from cfi.decision.templates import TEMPLATES, lint_library, lint_text, render
from tests.decision_builders import (
    DEFAULT_ACTIVITY,
    DEFAULT_SPECULATION,
    domains_for,
    make_payload,
)
from tests.unit.test_decision_regression import (
    BULLISH,
    CONF,
    PERMISSIVE,
    STRENGTH,
    perm,
    strength,
)


def _rng(seed: int) -> random.Random:
    """A seeded (reproducible) generator for test-state sampling; not used for anything secret."""
    return random.Random(seed)  # noqa: S311


CODES6 = ["S2", "S1", "N", "A1", "A2", "U"]
FLAGGED_CODES = [f"{c}{f}" for c in ("S2", "S1", "N", "A1", "A2") for f in ("", "~", "*")] + ["U"]
REGIMES = [
    "accumulation",
    "recovery",
    "expansion",
    "euphoria",
    "distribution",
    "capitulation",
    "mixed_unclear",
    None,
]
DERIV = ["low stress", "moderate stress", "elevated stress", "high stress", None]
VOL = ["normal", "notable_low", "notable_high", "extreme_high", "extreme_low", None]
ACTIVITY = [
    "quiet retail-proxy activity",
    "typical retail-proxy activity",
    "above-normal retail-proxy activity",
    "elevated retail-proxy activity",
    None,
]
SPEC = [
    "balanced",
    "short-biased speculative skew",
    "long-biased speculative skew",
    "strong short-biased speculative skew",
    "strong long-biased speculative skew",
    None,
]


def _random_state(rng: random.Random, scope: str = "BTC") -> tuple[list[str], dict[str, Any]]:
    n = len(domains_for(scope))
    codes = [rng.choice(FLAGGED_CODES) for _ in range(n)]
    ctx: dict[str, Any] = {
        "scope": scope,
        "regime": rng.choice(REGIMES),
        "derivatives": rng.choice(DERIV),
        "volatility": rng.choice(VOL),
        "extreme_other": rng.random() < 0.15,
        "activity": rng.choice(ACTIVITY),
        "speculation": rng.choice(SPEC),
        "has_conflicts": rng.random() < 0.1,
        "derivatives_freshness": rng.choice([None, None, "fresh", "stale"]),
    }
    return codes, ctx


def _assess(codes: list[str], **ctx: Any) -> AssessmentResult:
    scope = ctx.get("scope", "BTC")
    return assess(make_payload(codes, **ctx), scope)


def _is_clean(code: str) -> bool:
    return code == "U" or not any(c in code for c in "~*")


# ------------------------------------------------------------------------------------- INV-1
def test_inv1_unavailable_is_never_neutral() -> None:
    for codes in itertools.product(CODES6, repeat=5):
        r = _assess(list(codes))
        assert r.tally.u == codes.count("U")
        assert r.tally.n_neutral == codes.count("N")
        assert r.tally.d == 5 and r.tally.n == 5 - codes.count("U")
    base = _assess(["S1", "N", "S1", "N", "S1"])
    swapped = _assess(["S1", "U", "S1", "N", "S1"])
    assert (swapped.tally.n_neutral, swapped.tally.u, swapped.tally.n) == (
        base.tally.n_neutral - 1,
        base.tally.u + 1,
        base.tally.n - 1,
    )
    assert (swapped.tally.s, swapped.tally.a) == (base.tally.s, base.tally.a)


def test_inv1_unavailable_source_gives_not_assessed_never_low() -> None:
    r = _assess(["S1"] * 5, derivatives=None, volatility=None, activity=None, speculation=None)
    by_dim = {x.dimension.value: x.level for x in r.risks}
    assert (
        by_dim["leverage"] is by_dim["volatility"] is by_dim["narrative"] is RiskLevel.NOT_ASSESSED
    )
    everything_down = _assess(["U"] * 5, regime=None)
    market = next(x for x in everything_down.risks if x.dimension.value == "market")
    assert market.level is RiskLevel.NOT_ASSESSED


# ------------------------------------------------------------------------------------- INV-2
@pytest.mark.parametrize("ctx", [{}, {"regime": "euphoria"}])
def test_inv2_removing_neutral_or_unavailable_evidence_never_raises_stance(
    ctx: dict[str, Any],
) -> None:
    """Exhaustive 6^5: replace every neutral reading (each alone, and all together) by U."""
    for codes in itertools.product(CODES6, repeat=5):
        before = _assess(list(codes), **ctx)
        neutral_idx = [i for i, c in enumerate(codes) if c == "N"]
        variants = [[i] for i in neutral_idx]
        if len(neutral_idx) > 1:
            variants.append(neutral_idx)
        for idxs in variants:
            removed = [("U" if i in idxs else c) for i, c in enumerate(codes)]
            after = _assess(removed, **ctx)
            assert strength(after) <= strength(before), (codes, idxs)
            if strength(after) and strength(before):
                assert (after.final_stance in BULLISH) == (before.final_stance in BULLISH)


# ------------------------------------------------------------------------------------- INV-3
def test_inv3_removing_fresh_complete_evidence_never_raises_confidence() -> None:
    rng = _rng(38_203)
    for _ in range(6000):
        codes, ctx = _random_state(rng)
        before = _assess(codes, **ctx)
        for i, c in enumerate(codes):
            if c == "U" or not _is_clean(c):
                continue
            after = _assess([("U" if j == i else x) for j, x in enumerate(codes)], **ctx)
            assert CONF[after.confidence.value] <= CONF[before.confidence.value], (codes, ctx, i)


def test_inv3_documented_non_property_stale_removal_can_raise_confidence() -> None:
    """Removing a *stale* reading also removes its own downgrade, so confidence may rise. That is
    why Property B is stated for fresh, complete readings only (decision D-F)."""
    with_stale = _assess(["S1", "S1", "S1", "S1", "S1~"])
    without = _assess(["S1", "S1", "S1", "S1", "U"])
    assert CONF[without.confidence.value] >= CONF[with_stale.confidence.value] - 1
    assert "CN-03" in with_stale.confidence_rule_ids and "CN-03" not in without.confidence_rule_ids


# ------------------------------------------------------------------------------------- INV-4
def _worsen(rng: random.Random, ctx: dict[str, Any]) -> dict[str, Any] | None:
    """Increase the severity of one risk input that was assessed before."""
    options: list[tuple[str, list[Any]]] = [
        ("derivatives", ["low stress", "moderate stress", "elevated stress", "high stress"]),
        ("volatility", ["normal", "notable_high", "extreme_high"]),
        ("activity", ACTIVITY[:4]),
        ("speculation", SPEC[:2] + SPEC[2:3] + SPEC[4:5]),
    ]
    key, ladder = rng.choice(options)
    cur = ctx.get(key)
    if cur not in ladder:
        return None
    higher = ladder[ladder.index(cur) + 1 :]
    if not higher:
        return None
    out = dict(ctx)
    out[key] = rng.choice(higher)
    return out


def test_inv4_increasing_risk_never_gives_a_more_permissive_posture() -> None:
    rng = _rng(38_204)
    checked = 0
    for _ in range(8000):
        codes, ctx = _random_state(rng)
        worse = _worsen(rng, ctx)
        if worse is None:
            continue
        before, after = _assess(codes, **ctx), _assess(codes, **worse)
        checked += 1
        pb, pa = perm(before), perm(after)
        if pb is not None and pa is not None:
            assert pa <= pb, (codes, ctx, worse)
        assert after.tally == before.tally  # a risk change never touches the tally
        assert after.directional_stance_before_limits == before.directional_stance_before_limits
        assert strength(after) <= strength(before)
        rank = {"Low": 0, "Moderate": 1, "Elevated": 2, "High": 3}
        assert max(
            (rank[x.level.value] for x in after.risks if x.level.value in rank), default=0
        ) >= max((rank[x.level.value] for x in before.risks if x.level.value in rank), default=0)
    assert checked > 500


# ------------------------------------------------------------------------------------- INV-5
def test_inv5_regime_is_never_a_directional_vote() -> None:
    for codes in itertools.product(CODES6, repeat=5):
        base = _assess(list(codes))
        for regime in ("expansion", "euphoria", "distribution", None):
            r = _assess(list(codes), regime=regime)
            assert r.tally == base.tally
            assert r.directional_stance_before_limits == base.directional_stance_before_limits
            assert r.conflict == base.conflict
            assert r.coverage_available == base.coverage_available
            if regime is None and base.directional_stance_before_limits is not Stance.INSUFFICIENT:
                assert (
                    r.final_stance is not Stance.INSUFFICIENT
                    or base.final_stance is Stance.INSUFFICIENT
                )
        if codes.count("U") <= 2:
            # a missing regime alone never forces Insufficient Evidence
            assert _assess(list(codes), regime=None).final_stance is not Stance.INSUFFICIENT or (
                base.final_stance is Stance.INSUFFICIENT
            )


# ------------------------------------------------------------------------------------- INV-6
def test_inv6_risk_never_independently_creates_a_directional_stance() -> None:
    rng = _rng(38_206)
    for _ in range(6000):
        codes, ctx = _random_state(rng)
        base_ctx = dict(
            ctx,
            derivatives="low stress",
            volatility="normal",
            extreme_other=False,
            activity=DEFAULT_ACTIVITY,
            speculation=DEFAULT_SPECULATION,
            regime="expansion",
        )
        a, b = _assess(codes, **ctx), _assess(codes, **base_ctx)
        assert a.directional_stance_before_limits == b.directional_stance_before_limits
        assert a.tally == b.tally
        raw = a.directional_stance_before_limits
        if raw in BULLISH:
            assert strength(a) <= STRENGTH[raw.value]
            assert a.final_stance in BULLISH or a.final_stance is Stance.NEUTRAL
        else:  # bearish, neutral and insufficient raw stances are never altered by caps
            assert a.final_stance is raw


# ------------------------------------------------------------------------------------- INV-7
def test_inv7_insufficient_coverage_cannot_produce_a_directional_stance() -> None:
    for scope in ("BTC", "SOL"):
        n = len(domains_for(scope))
        for codes in itertools.product(CODES6, repeat=n):
            r = _assess(list(codes), scope=scope)
            below = 2 * r.tally.n < r.tally.d
            assert (r.final_stance is Stance.INSUFFICIENT) is below
            assert (r.confidence is Confidence.INSUFFICIENT) is below
            assert (r.posture is Posture.INVESTIGATE_FURTHER) is below
            if below:
                assert r.conflict is False
                assert "STANCE.Insufficient Evidence" in r.explanation.directional
                assert r.missing


# ------------------------------------------------------------------------------------- INV-8
def test_inv8_qualifying_conflict_cannot_disappear() -> None:
    for codes in itertools.product(CODES6, repeat=5):
        r = _assess(list(codes))
        s = sum(c.startswith("S") for c in codes)
        a = sum(c.startswith("A") for c in codes)
        strong_s, strong_a = codes.count("S2") > 0, codes.count("A2") > 0
        qualifies = (s >= 2 and a >= 2) or (strong_s and strong_a)
        if r.tally.n * 2 >= r.tally.d and qualifies:
            assert r.conflict and r.final_stance is Stance.NEUTRAL
            assert "CONFLICT.phrase" in r.explanation.directional
            assert r.posture is Posture.WAIT_FOR_CONFIRMATION
        else:
            assert "CONFLICT.phrase" not in r.explanation.directional


# ------------------------------------------------------------------------------------- INV-9
_FIELD_ID = re.compile(r"^get_[a-z_]+(\.[a-z_]+|\[\d+\])*(\.assets\[\d+\])?[A-Za-z_.\[\]0-9]*$")


def test_inv9_every_item_is_traceable_to_field_ids() -> None:
    rng = _rng(38_209)
    for _ in range(1500):
        codes, ctx = _random_state(rng)
        r = _assess(codes, **ctx)
        items = (*r.supportive, *r.adverse, *r.neutral)
        assert len(items) == r.tally.n  # evidence count equals n
        for item in items:
            assert item.field_ids and all(_FIELD_ID.match(f) for f in item.field_ids)
            assert item.reason_ids and item.template_id in TEMPLATES
            if item.domain in ("institutional", "whale"):  # band is not a citable field: raw path
                assert item.raw_paths
        for cap in r.observed_caps:
            assert cap.source_field_ids and cap.reason_id.startswith(cap.rule_id)
        for rec in r.cap_u:
            assert rec.source_field_id and rec.rule_id and rec.reason_id
        for risk in r.risks:
            assert risk.reason_ids
        # every template id the engine can emit exists in the library (no free-form prose)
        for tid in r.explanation.all_template_ids():
            assert tid in TEMPLATES
        assert all(isinstance(x, str) for x in r.fired_rule_ids)


def test_inv9_unavailable_readings_are_listed_not_hidden() -> None:
    r = _assess(["U", "S1", "S1", "S1", "S1"])
    assert r.missing == ("institutional",)
    assert "DIR.institutional.U" in r.explanation.missing_context
    unavailable = [x for x in r.readings if x.domain == "institutional"]
    assert unavailable and unavailable[0].status == "unavailable"


# ------------------------------------------------------------------------------------- INV-10
def test_inv10_assessment_is_deterministic() -> None:
    rng = _rng(38_210)
    for _ in range(300):
        codes, ctx = _random_state(rng)
        payload = make_payload(codes, **ctx)
        first = assess(payload, ctx["scope"])
        again = assess(copy.deepcopy(payload), ctx["scope"])
        assert first == again
        # a re-ordered copy (dict key order, tool order) gives the same assessment
        shuffled = dict(reversed(list(payload.items())))
        shuffled["tool_results"] = dict(reversed(list(payload["tool_results"].items())))
        reordered = assess(shuffled, ctx["scope"])
        assert reordered == first  # hash uses sorted keys, so even the provenance hash matches


def test_inv10_assess_does_not_mutate_its_input_and_has_no_side_effects() -> None:
    payload = make_payload(["S1", "S2", "N", "A1", "S1"])
    snapshot = copy.deepcopy(payload)
    assess(payload, "BTC")
    assert payload == snapshot


def test_inv10_versions_are_part_of_the_result() -> None:
    r = _assess(["S1"] * 5)
    assert (r.methodology_version, r.parameter_version, r.template_version) == (
        "decision_methodology.v0",
        "decision_params.v0",
        "decision_templates.v0",
    )


# ------------------------------------------------------------------------------------- INV-11
def test_inv11_removing_a_cap_source_never_strengthens_stance_or_loosens_posture() -> None:
    sources = ("regime", "derivatives", "volatility")
    rng = _rng(38_211)
    removals = 0
    for _ in range(4000):
        codes, ctx = _random_state(rng)
        ctx = {
            **ctx,
            "regime": rng.choice(REGIMES[:-1]),
            "derivatives": rng.choice(DERIV[:-1]),
            "volatility": rng.choice(VOL[:-1]),
        }
        before = _assess(codes, **ctx)
        for n in (1, 2, 3):
            for subset in itertools.combinations(sources, n):
                after = _assess(codes, **{**ctx, **dict.fromkeys(subset)})
                removals += 1
                assert strength(after) <= strength(before), (codes, ctx, subset)
                pb, pa = perm(before), perm(after)
                if pb is not None and pa is not None:
                    assert pa <= pb, (codes, ctx, subset)
                assert after.tally == before.tally
                assert (
                    after.directional_stance_before_limits
                    == before.directional_stance_before_limits
                )
                if before.directional_stance_before_limits not in BULLISH:
                    assert after.final_stance == before.final_stance
    assert removals > 10_000


def test_inv11_exhaustive_readings_default_context() -> None:
    for codes in itertools.product(CODES6, repeat=5):
        full = _assess(list(codes))
        for subset in (
            (("regime",)),
            ("derivatives",),
            ("volatility",),
            ("regime", "derivatives", "volatility"),
        ):
            after = _assess(list(codes), **dict.fromkeys(subset))
            assert strength(after) <= strength(full)
            pf, pa = perm(full), perm(after)
            if pf is not None and pa is not None:
                assert pa <= pf


# ------------------------------------------------------------------------------------- extras
def test_confidence_is_one_of_four_words_never_a_percentage() -> None:
    rng = _rng(38_212)
    for _ in range(500):
        codes, ctx = _random_state(rng)
        r = _assess(codes, **ctx)
        assert isinstance(r.confidence, Confidence)
        assert not re.search(r"[0-9%]", r.confidence.value)


def test_posture_is_one_of_the_six_approved_labels_only() -> None:
    assert {p.value for p in Posture} == {
        "INVESTIGATE FURTHER",
        "WAIT FOR CONFIRMATION",
        "MONITOR CONSTRUCTIVE CONDITIONS",
        "MONITOR WITH ELEVATED CAUTION",
        "AVOID ADDING HIGH-RISK EXPOSURE",
        "REASSESS / REDUCE RISK",
    }
    rng = _rng(38_213)
    for _ in range(1500):
        codes, ctx = _random_state(rng)
        r = _assess(codes, **ctx)
        assert r.posture.value in {p.value for p in Posture}
        assert r.final_stance in set(Stance)
        # INSUFFICIENT <=> INVESTIGATE FURTHER
        assert (r.final_stance is Stance.INSUFFICIENT) == (r.posture is Posture.INVESTIGATE_FURTHER)


def test_constructive_posture_needs_complete_fresh_evidence_and_readable_cap_sources() -> None:
    """P13: MONITOR CONSTRUCTIVE CONDITIONS only with every directional reading present, fresh and
    complete, and every cap source evaluable."""
    reached = 0
    for codes in itertools.product(FLAGGED_CODES[:], repeat=3):
        full = [*codes, "S1", "S1"]
        r = _assess(full)
        if r.posture is Posture.MONITOR_CONSTRUCTIVE:
            reached += 1
            assert all(_is_clean(c) and c != "U" for c in full)
    assert reached > 0
    rng = _rng(38_214)
    for _ in range(3000):
        sampled, ctx = _random_state(rng)
        r = _assess(sampled, **ctx)
        if r.posture is Posture.MONITOR_CONSTRUCTIVE:
            assert all(c != "U" and _is_clean(c) for c in sampled)
            assert not r.missing_context and r.confidence is Confidence.HIGH
            assert r.final_stance in (Stance.BULLISH, Stance.STRONGLY_BULLISH)


def test_caps_never_create_or_alter_a_bearish_stance() -> None:
    rng = _rng(38_215)
    for _ in range(4000):
        codes, ctx = _random_state(rng)
        r = _assess(codes, **ctx)
        if r.directional_stance_before_limits.value.endswith("Bearish"):
            assert r.final_stance is r.directional_stance_before_limits and not r.observed_caps
        assert not r.final_stance.value.endswith("Bearish") or (
            r.directional_stance_before_limits is r.final_stance
        )


def test_derivatives_freshness_not_assessed_is_distinct_from_stale_and_unavailable() -> None:
    rng = _rng(38_216)
    for _ in range(1500):
        codes, ctx = _random_state(rng)
        ctx = {**ctx, "derivatives": "low stress", "derivatives_freshness": None}
        not_assessed = _assess(codes, **ctx)
        fresh = _assess(codes, **{**ctx, "derivatives_freshness": "fresh"})
        stale = _assess(codes, **{**ctx, "derivatives_freshness": "stale"})
        # not_assessed behaves exactly like fresh (never CU-02, never CN-03, no floor)...
        assert not_assessed.final_stance == fresh.final_stance
        assert not_assessed.confidence == fresh.confidence
        assert not_assessed.posture == fresh.posture
        assert [x.level for x in not_assessed.risks] == [x.level for x in fresh.risks]
        assert all(c.rule_id != "CU-02" for c in not_assessed.cap_u)
        # ...and stale can only lower confidence or raise risk, never the reverse
        assert CONF[stale.confidence.value] <= CONF[fresh.confidence.value]
        for s_risk, f_risk in zip(stale.risks, fresh.risks, strict=True):
            order = ["Not assessed", "Low", "Moderate", "Elevated", "High"]
            assert order.index(s_risk.level.value) >= order.index(f_risk.level.value)


def test_cap_u_depends_only_on_availability_not_on_quality_flags() -> None:
    rng = _rng(38_217)
    for _ in range(1200):
        codes, ctx = _random_state(rng)
        clean = [c.replace("~", "").replace("*", "") for c in codes]
        flagged_ctx = {**ctx, "has_conflicts": True}
        a = _assess(codes, **flagged_ctx)
        b = _assess(clean, **ctx)
        if (
            a.directional_stance_before_limits in BULLISH
            and b.directional_stance_before_limits in BULLISH
        ):
            assert {c.rule_id for c in a.cap_u} == {c.rule_id for c in b.cap_u}


def test_posture_rank_table_matches_the_documented_ordering() -> None:
    assert (
        PERMISSIVE["MONITOR CONSTRUCTIVE CONDITIONS"] > PERMISSIVE["MONITOR WITH ELEVATED CAUTION"]
    )
    assert (
        PERMISSIVE["MONITOR WITH ELEVATED CAUTION"] > PERMISSIVE["AVOID ADDING HIGH-RISK EXPOSURE"]
    )
    assert PERMISSIVE["AVOID ADDING HIGH-RISK EXPOSURE"] > PERMISSIVE["WAIT FOR CONFIRMATION"]
    assert PERMISSIVE["WAIT FOR CONFIRMATION"] > PERMISSIVE["REASSESS / REDUCE RISK"]
    assert "INVESTIGATE FURTHER" not in PERMISSIVE  # outside the ordering


# ------------------------------------------------------------------------------------- scopes
def test_undefined_scope_is_rejected_and_scope_definitions_set_d() -> None:
    with pytest.raises(ValueError, match="unsupported scope"):
        assess(make_payload(["S1"] * 5), "DOGE")
    assert _assess(["S1"] * 5).expected_domains == 5
    sol = assess(make_payload(["S1"] * 4, scope="SOL"), "SOL")
    assert sol.expected_domains == 4 and sol.tally.d == 4  # whale removed from D, not negative


# ------------------------------------------------------------------------------------- templates
def test_template_library_passes_the_lint() -> None:
    assert len(TEMPLATES) == 118
    assert lint_library() == {}


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("You should buy now.", "TL-01"),
        ("Time to sell.", "TL-02"),
        ("A long-term view.", "TL-03"),
        ("Go short here.", "TL-04"),
        ("This is guaranteed.", "TL-05"),
        ("Prices will rise.", "TL-06"),
        ("A price target is set.", "TL-07"),
        ("There is a high probability.", "TL-08"),
        ("Moves by 5 percent.", "TL-09"),
        ("This is bullish.", "TL-10"),
        ("Add to the position.", "TL-11"),
    ],
)
def test_template_lint_catches_each_prohibited_pattern(text: str, rule: str) -> None:
    assert rule in lint_text(text)


def test_template_lint_exemption_is_exact_and_narrow() -> None:
    for tid in ("STANCE.note", "CONF.note", "POSTURE.note"):
        assert lint_text(TEMPLATES[tid], exact_exempt=True) == []
    assert lint_text(TEMPLATES["STANCE.note"]) != []  # the same text is flagged without exemption


def test_assembled_text_for_every_assessment_passes_the_lint() -> None:
    """Concatenations the assembler can produce (explanation + fixed disclaimers) are linted too."""
    rng = _rng(38_218)
    note_ids = {"STANCE.note", "CONF.note", "POSTURE.note"}
    for _ in range(800):
        codes, ctx = _random_state(rng)
        r = _assess(codes, **ctx)
        ids = (
            *r.explanation.all_template_ids(),
            *(x.template_id for x in r.risks if x.template_id),
            f"STANCE.{r.final_stance.value}",
            f"CONF.{r.confidence.value}",
            f"POSTURE.{r.posture.value}",
        )
        for tid in ids:
            assert lint_text(TEMPLATES[tid], exact_exempt=tid in note_ids) == [], tid
        text = render([t for t in ids if t not in note_ids])
        assert lint_text(text) == [], text


def test_missing_data_is_never_described_as_bearish() -> None:
    r = _assess(["S1", "S1", "S1", "S1", "S1"], regime=None, derivatives=None, volatility=None)
    for tid in r.explanation.all_template_ids():
        assert not re.search(
            r"bearish|adverse|negative", TEMPLATES[tid], re.IGNORECASE
        ) or tid.startswith("STANCE.")
    assert r.explanation.limits and r.explanation.missing_context
