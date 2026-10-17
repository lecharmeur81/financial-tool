"""Phase 51 Stage 2 — the pure investment-alert evaluator (no database, no network, no clock).

Fixtures G01 to G08 (case (a): evaluator level), G27, G28, G29, G30, G31, G33, G40, G41, G42,
G43 and G55 of ``METHODOLOGY_INVESTMENT_ALERTS.md`` (revision 6). The lifecycle fixtures (dedup,
cooldown, re-arm) belong to Stage 3 and everything involving ``AlertService`` to Stage 6.

States 2 (``candidate_invalidation_triggered``) and 8 (``candidate_no_findings_detected``) are not
reachable through valid public contracts, so they are hand-built only. The original G32
(derivatives-only supporting evidence) is NOT CONSTRUCTIBLE under the Phase 45-49 contracts and is
not built; its constructible risk-role variant is pinned below. Nothing in this file validates
persistence.
"""

from __future__ import annotations

import ast
import copy
import dataclasses
import inspect
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import cfi.alerts.investment_alerts as ia
from cfi.alerts.investment_alerts import evaluate_investment_alerts as evaluate
from cfi.alerts.universe import BANNED_PATTERNS
from tests.investment_alert_builders import (
    AS_OF,
    CHECKS_NOT_EVALUATED,
    KNOWLEDGE_TIME,
    NOT_A_THESIS,
    NOW,
    PAYLOAD_HASH,
    ROW_ID,
    SCOPES,
    SOURCE_CONTRACTS,
    UUID,
    decision,
    ref,
    stored,
)

ALERTABLE = ia.ALERTABLE_STATES
NAIVE = datetime(2026, 10, 11, 11, 0)  # noqa: DTZ001 — a naive time is the case under test
Mutate = Callable[[dict[str, Any]], None]


def _run(d: object, **stored_overrides: Any) -> ia.InvestmentEvaluation:
    return evaluate(d, stored(**stored_overrides), now=NOW)


def _btc(state: str, mutate: Mutate | None = None) -> ia.AssetOutcome:
    """Evaluate a decision whose every asset is in ``state``; return the BTC outcome."""
    return _run(decision(state, mutate=mutate)).outcomes[0]


# ------------------------------------------------------------------ G01 to G08 (a): the 8 states
@pytest.mark.parametrize("state", ALERTABLE)
def test_every_alertable_state_is_class_a_with_a_validated_candidate(state: str) -> None:
    result = _run(decision(state))
    assert not result.refused
    assert [o.asset for o in result.outcomes] == list(SCOPES)
    for o in result.outcomes:
        assert (o.outcome_class, o.reason, o.state) == ("A", None, state)
        c = o.candidate
        assert c is not None
        assert (c.asset, c.state, c.severity, c.observed_value) == (
            o.asset,
            state,
            "notable",
            state,
        )
        assert c.dedup_key == f"investment_state:{o.asset}"
        # copied verbatim from Phase 48: a non-candidate (state 3) has no assessment
        assert c.component_status == (
            "not_applicable" if state == "contradicted_evidence" else "assessed"
        )
        assert c.detection_method == ia.DETECTION_METHOD_EVALUATOR
    assert result.count("A") == 4
    assert len(result.candidates) == 4


@pytest.mark.parametrize("state", ["insufficient_evidence", "no_opportunity"])
def test_non_alertable_evaluated_states_are_class_c(state: str) -> None:
    result = _run(decision(state))
    assert not result.refused
    assert {(o.outcome_class, o.reason) for o in result.outcomes} == {("C", "not_alertable_state")}
    assert result.candidates == ()
    assert result.count("C") == 4


def test_a_candidate_level_withheld_state_is_class_b() -> None:
    result = _run(
        decision({"BTC": "withheld_integrity_gate", **dict.fromkeys(SCOPES[1:], "no_opportunity")})
    )
    assert (result.outcomes[0].outcome_class, result.outcomes[0].reason) == (
        "B",
        "candidate_withheld",
    )
    assert result.outcomes[0].state == "withheld_integrity_gate"
    assert all(o.outcome_class == "C" for o in result.outcomes[1:])


def test_a_request_wide_gate_is_class_b_for_every_asset() -> None:
    result = _run(decision(performed=False))
    assert not result.refused
    assert {(o.outcome_class, o.reason, o.state) for o in result.outcomes} == {
        ("B", "request_gated", "withheld_integrity_gate")
    }
    assert result.candidates == ()


def test_mixed_states_are_independent_per_asset() -> None:
    states = {
        "BTC": "candidate_risk_findings_detected",
        "ETH": "contradicted_evidence",
        "SOL": "insufficient_evidence",
        "XRP": "withheld_integrity_gate",
    }
    got = {o.asset: (o.outcome_class, o.reason) for o in _run(decision(states)).outcomes}
    assert got == {
        "BTC": ("A", None),
        "ETH": ("A", None),
        "SOL": ("C", "not_alertable_state"),
        "XRP": ("B", "candidate_withheld"),
    }


# ------------------------------------------------------------------ G43: adverse confirmation
def test_confirmed_adverse_evidence_is_no_opportunity_and_not_alertable() -> None:
    def adverse(d: dict[str, Any]) -> None:
        for s in SCOPES:
            d["assets"][s]["reasons"] = ["OD-ADVERSE-CONFIRMATION"]

    o = _btc("no_opportunity", adverse)
    assert (o.outcome_class, o.reason, o.candidate) == ("C", "not_alertable_state", None)


@pytest.mark.parametrize(
    "reason", ["OD-UNCONFIRMED", "OD-NO-ASSET-SPECIFIC-CONFIRMER", "OD-UNVERIFIED-SUPPORT", "X"]
)
def test_no_opportunity_is_class_c_whatever_the_phase_46_reason(reason: str) -> None:
    def set_reason(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["reasons"] = [reason]

    assert _btc("no_opportunity", set_reason).outcome_class == "C"


# ------------------------------------------------------------------ G31: required fields (§6.1)
def _drop(path: tuple[str, ...]) -> Mutate:
    def mutate(d: dict[str, Any]) -> None:
        node: Any = d["assets"]["BTC"]
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = None if path[-1] in {"risk_findings", "invalidation"} else node[path[-1]]
        if path[-1] not in {"risk_findings", "invalidation"}:
            del node[path[-1]]

    return mutate


CANDIDATES = (
    "candidate_invalidation_triggered",
    "candidate_risk_findings_detected",
    "candidate_unresolved",
    "candidate_no_findings_detected",
)


@pytest.mark.parametrize("state", CANDIDATES)
@pytest.mark.parametrize("field", ["risk_findings", "invalidation"])
def test_null_risk_blocks_on_a_candidate_state_are_incomplete(state: str, field: str) -> None:
    o = _btc(state, _drop((field,)))
    assert (o.outcome_class, o.reason, o.candidate) == ("B", "incomplete_decision", None)


@pytest.mark.parametrize("state", ALERTABLE)
@pytest.mark.parametrize(
    "path",
    [
        ("risk_assessment",),
        ("risk_assessment", "state"),
        ("evidence",),
        ("evidence", "supporting"),
        ("decision_reasons",),
    ],
)
def test_a_missing_required_field_is_incomplete_never_an_alert(
    state: str, path: tuple[str, ...]
) -> None:
    o = _btc(state, _drop(path))
    assert (o.outcome_class, o.reason, o.candidate) == ("B", "incomplete_decision", None)


def test_contradicted_evidence_needs_the_contradicting_list() -> None:
    o = _btc("contradicted_evidence", _drop(("evidence", "contradicting")))
    assert (o.outcome_class, o.reason) == ("B", "incomplete_decision")


def test_contradicted_evidence_does_not_need_the_risk_blocks() -> None:
    o = _btc("contradicted_evidence")
    assert o.outcome_class == "A"
    assert o.candidate is not None


@pytest.mark.parametrize("state", ["candidate_unresolved", "candidate_no_findings_detected"])
@pytest.mark.parametrize("missing", [NOT_A_THESIS, CHECKS_NOT_EVALUATED])
def test_states_7_and_8_must_carry_the_two_standing_reasons(state: str, missing: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["decision_reasons"].remove(missing)

    assert _btc(state, mutate).reason == "incomplete_decision"


@pytest.mark.parametrize("value", ["", " ", " assessed", None, 5, ["assessed"]])
def test_an_unusable_risk_assessment_state_is_incomplete(value: object) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["risk_assessment"]["state"] = value

    assert _btc("candidate_unresolved", mutate).reason == "incomplete_decision"


def test_the_component_status_is_the_risk_assessment_state_verbatim() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["risk_assessment"]["state"] = "assessed_partially"

    c = _btc("candidate_unresolved", mutate).candidate
    assert c is not None
    assert c.component_status == "assessed_partially"


# ------------------------------------------------------------------ G27, G28, G33: freshness guard
@pytest.mark.parametrize("state", ALERTABLE)
@pytest.mark.parametrize("bad", [False, None, "true", 1, 0, "fresh"])
def test_unverified_supporting_evidence_is_class_b(state: str, bad: object) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["evidence"]["supporting"][0]["freshness_verified"] = bad

    o = _btc(state, mutate)
    assert (o.outcome_class, o.reason, o.candidate) == ("B", "evidence_freshness_unverified", None)


def test_a_missing_freshness_flag_is_unverified_not_neutral() -> None:
    def mutate(d: dict[str, Any]) -> None:
        del d["assets"]["BTC"]["evidence"]["supporting"][0]["freshness_verified"]

    assert _btc("candidate_unresolved", mutate).reason == "evidence_freshness_unverified"


def test_one_unverified_reference_among_verified_ones_blocks_the_alert() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["evidence"]["supporting"].append(ref("get_x.data.BTC.z", verified=False))

    assert _btc("candidate_unresolved", mutate).reason == "evidence_freshness_unverified"


def test_unverified_contradicting_evidence_blocks_state_3() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["evidence"]["contradicting"][0]["freshness_verified"] = False

    assert _btc("contradicted_evidence", mutate).reason == "evidence_freshness_unverified"


@pytest.mark.parametrize("state", ALERTABLE)
def test_empty_supporting_evidence_is_class_b(state: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["evidence"]["supporting"] = []

    assert _btc(state, mutate).reason == "evidence_freshness_unverified"


def test_empty_contradicting_evidence_blocks_state_3() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["evidence"]["contradicting"] = []

    assert _btc("contradicted_evidence", mutate).reason == "evidence_freshness_unverified"


def test_unverified_other_or_missing_evidence_does_not_block() -> None:
    def mutate(d: dict[str, Any]) -> None:
        e = d["assets"]["BTC"]["evidence"]
        e["other_eligible"] = [ref("get_o.data.a", verified=False)]
        e["missing_or_unusable"] = [ref("get_m.data.a", verified=False)]

    assert _btc("candidate_unresolved", mutate).outcome_class == "A"


def test_only_the_asset_with_unverified_evidence_is_blocked() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["ETH"]["evidence"]["supporting"][0]["freshness_verified"] = False

    got = {
        o.asset: o.outcome_class
        for o in _run(decision("candidate_unresolved", mutate=mutate)).outcomes
    }
    assert got == {"BTC": "A", "ETH": "B", "SOL": "A", "XRP": "A"}


def test_no_age_threshold_exists_a_very_old_but_fresh_reading_is_not_refused() -> None:
    def mutate(d: dict[str, Any]) -> None:
        r = d["assets"]["BTC"]["evidence"]["supporting"][0]
        r["freshness_records"] = [{"status": "fresh", "age_seconds": 10**9}]

    assert _btc("candidate_unresolved", mutate).outcome_class == "A"
    old = datetime(2001, 1, 1, tzinfo=UTC)
    result = _run(decision("candidate_unresolved"), as_of=old, knowledge_time=old)
    assert not result.refused
    assert result.count("A") == 4


# ------------------------------------------------------------------ G29: cycle-level time refusals
def _expect_refusal(result: ia.InvestmentEvaluation, reason: str) -> None:
    assert result.refused
    assert result.refusal_reason == reason
    assert result.outcomes == ()
    assert result.candidates == ()


@pytest.mark.parametrize("field", ["as_of", "knowledge_time"])
@pytest.mark.parametrize("bad", [None, NAIVE, "2026-10-11T11:00:00+00:00"])
def test_a_missing_or_naive_snapshot_time_refuses_the_whole_evaluation(
    field: str, bad: object
) -> None:
    _expect_refusal(_run(decision(), **{field: bad}), "snapshot_time_invalid")


@pytest.mark.parametrize("field", ["as_of", "knowledge_time"])
def test_a_snapshot_time_later_than_now_refuses(field: str) -> None:
    _expect_refusal(
        _run(decision(), **{field: NOW + timedelta(seconds=1)}), "snapshot_time_in_future"
    )


def test_equal_to_now_is_not_in_the_future() -> None:
    assert not _run(decision(), as_of=NOW, knowledge_time=NOW).refused


@pytest.mark.parametrize("now", [None, NAIVE, "now", 0])
def test_a_missing_or_naive_now_refuses(now: object) -> None:
    result = evaluate(decision(), stored(), now=now)  # type: ignore[arg-type]
    _expect_refusal(result, "snapshot_time_invalid")


def test_now_and_the_snapshot_times_never_change_the_candidates() -> None:
    base = _run(decision("candidate_unresolved"))
    later = evaluate(
        decision("candidate_unresolved"),
        stored(
            as_of=AS_OF - timedelta(days=30), knowledge_time=KNOWLEDGE_TIME - timedelta(days=30)
        ),
        now=NOW + timedelta(days=365),
    )
    assert base == later  # G41: no timestamp is substituted into, or read as, evidence freshness
    assert not any(
        isinstance(getattr(o.candidate, f.name, None), datetime)
        for o in base.outcomes
        if o.candidate
        for f in dataclasses.fields(o.candidate)
    )


# ------------------------------------------------------------------ G30: identity
@pytest.mark.parametrize(
    "overrides",
    [
        {"row_id": ROW_ID + 1},
        {"uuid": "00000000-0000-0000-0000-000000000000"},
        {"payload_hash": "cd" * 32},
    ],
)
def test_a_snapshot_identity_that_differs_from_the_stored_row_refuses(
    overrides: dict[str, Any],
) -> None:
    _expect_refusal(_run(decision(), **overrides), "snapshot_identity_mismatch")


@pytest.mark.parametrize("key", ["row_id", "uuid", "producer_payload_hash"])
@pytest.mark.parametrize("value", [None, "", 0, True, [1]])
def test_a_missing_or_wrong_identity_in_the_decision_refuses(key: str, value: object) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["snapshot"][key] = value

    _expect_refusal(_run(decision(mutate=mutate)), "snapshot_identity_mismatch")


@pytest.mark.parametrize("key", ["uuid", "producer_payload_hash"])
def test_a_padded_text_identity_in_the_decision_refuses(key: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["snapshot"][key] = " padded "

    _expect_refusal(_run(decision(mutate=mutate)), "snapshot_identity_mismatch")


def test_a_boolean_row_id_is_not_an_identity() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["snapshot"]["row_id"] = True

    _expect_refusal(_run(decision(mutate=mutate), row_id=1), "snapshot_identity_mismatch")


def test_a_stored_identity_of_the_wrong_type_refuses() -> None:
    result = evaluate(decision(), None, now=NOW)  # type: ignore[arg-type]
    _expect_refusal(result, "snapshot_identity_mismatch")


@pytest.mark.parametrize("key", ["uuid", "producer_payload_hash"])
@pytest.mark.parametrize("bad", [None, "", " padded "])
def test_equal_but_invalid_text_identities_refuse(key: str, bad: object) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["snapshot"][key] = bad

    stored_key = "payload_hash" if key == "producer_payload_hash" else key
    result = _run(decision(mutate=mutate), **{stored_key: bad})
    _expect_refusal(result, "snapshot_identity_mismatch")


@pytest.mark.parametrize("key", ["uuid", "payload_hash"])
@pytest.mark.parametrize("bad", [None, "", " padded "])
def test_an_invalid_stored_text_identity_refuses_against_a_valid_decision(
    key: str, bad: object
) -> None:
    _expect_refusal(_run(decision(), **{key: bad}), "snapshot_identity_mismatch")


def test_a_boolean_stored_row_id_never_matches_the_integer_one() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["snapshot"]["row_id"] = 1

    _expect_refusal(_run(decision(mutate=mutate), row_id=True), "snapshot_identity_mismatch")


def test_a_valid_matching_identity_still_yields_candidates() -> None:
    result = _run(decision("candidate_risk_findings_detected"))
    assert not result.refused
    assert len(result.candidates) == len(SCOPES)


# ------------------------------------------------------------------ G32 (risk-role variant)
def test_risk_finding_with_unverified_freshness_stays_admissible_and_adds_no_marker() -> None:
    """Original G32 (derivatives-only *supporting* evidence) is NOT CONSTRUCTIBLE: derivatives is
    ``Role.RISK`` and can never be Phase 49 ``supporting``. The constructible variant is pinned
    here: section 5.3 guards ``supporting`` only, so a risk finding with
    ``freshness_verified=False`` stays class A. The flag is not carried into the candidate."""
    state = "candidate_risk_findings_detected"

    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["risk_findings"]["detected"] = [
            {
                "check_id": "RI-LEV-01",
                "result": "detected",
                "freshness_verified": False,
                "field_ids": ["get_deriv.data.x"],
            }
        ]

    baseline = _btc(state)
    o = _btc(state, mutate)
    assert (o.outcome_class, o.reason, o.state) == ("A", None, state)
    assert o.candidate is not None
    assert baseline.candidate is not None
    assert "get_deriv.data.x" in o.candidate.evidence_field_ids
    assert o.candidate.detection_method == baseline.candidate.detection_method
    assert o.candidate.component_status == baseline.candidate.component_status
    assert {f.name for f in dataclasses.fields(o.candidate)} == {
        "asset",
        "state",
        "component_status",
        "evidence_field_ids",
        "detection_method",
    }  # no field could carry the unverified-freshness flag
    assert "freshness" not in repr(o.candidate)


# ------------------------------------------------------------------ contract refusals
def _bad(mutate: Mutate) -> dict[str, Any]:
    return decision(mutate=mutate)


def _del(*path: str) -> Mutate:
    def mutate(d: dict[str, Any]) -> None:
        node: Any = d
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]

    return mutate


def _set(value: object, *path: str) -> Mutate:
    def mutate(d: dict[str, Any]) -> None:
        node: Any = d
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value

    return mutate


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        "investment_decision.v0",
        7,
        {},
        _bad(_set("investment_decision.v1", "contract_version")),
        _bad(_del("contract_version")),
        _bad(_del("assets")),
        _bad(_set([], "assets")),
        _bad(_del("assets", "XRP")),
        _bad(_set(decision()["assets"]["BTC"], "assets", "DOGE")),
        _bad(_set("not_a_state", "assets", "BTC", "decision_state")),
        _bad(_set(None, "assets", "BTC", "decision_state")),
        _bad(_set(["x"], "assets", "BTC")),
        _bad(_del("assessment")),
        _bad(_set({"performed": "yes"}, "assessment")),
        _bad(_set({"performed": None}, "assessment")),
        _bad(_del("parameters")),
        _bad(_set("investment_states.v1", "parameters", "states_version")),
        _bad(_set("investment_params.v1", "parameters", "version")),
        _bad(_del("snapshot")),
        _bad(_del("source_contracts")),
        _bad(_del("source_contracts", "risk")),
        _bad(_set("", "source_contracts", "ranking")),
        _bad(_set(5, "source_contracts", "unified")),
    ],
)
def test_an_unusable_decision_is_a_cycle_refusal_and_never_raises(bad: object) -> None:
    _expect_refusal(_run(bad), "decision_contract_invalid")


def test_a_gated_request_with_a_non_withheld_asset_is_inconsistent() -> None:
    d = decision(performed=False)
    d["assets"]["BTC"]["decision_state"] = "candidate_unresolved"
    _expect_refusal(_run(d), "decision_contract_invalid")


def test_the_order_of_the_asset_keys_does_not_matter() -> None:
    d = decision("candidate_unresolved")
    d["assets"] = dict(reversed(list(d["assets"].items())))
    assert [o.asset for o in _run(d).outcomes] == list(SCOPES)


# ------------------------------------------------------------------ G55: partition
@pytest.mark.parametrize("state", [*ALERTABLE, *ia.NON_ALERTABLE_STATES])
def test_every_state_falls_into_exactly_one_class(state: str) -> None:
    expected = {
        **dict.fromkeys(ALERTABLE, "A"),
        "withheld_integrity_gate": "B",
        "insufficient_evidence": "C",
        "no_opportunity": "C",
    }[state]
    result = _run(decision(state))
    assert {o.outcome_class for o in result.outcomes} == {expected}
    assert sum(result.count(c) for c in ia.OUTCOME_CLASSES) == len(SCOPES)


def test_refusals_and_classes_never_overlap() -> None:
    refused = _run(decision(), uuid="x")
    assert refused.refused
    assert sum(refused.count(c) for c in ia.OUTCOME_CLASSES) == 0
    ok = _run(decision())
    assert not ok.refused
    assert sum(ok.count(c) for c in ia.OUTCOME_CLASSES) == len(SCOPES)


def test_outcome_and_evaluation_objects_enforce_their_own_shape() -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.AssetOutcome("BTC", "A", "candidate_unresolved", None, None)
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.AssetOutcome("BTC", "B", "no_opportunity", "made_up_reason", None)
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.AssetOutcome("BTC", "C", "no_opportunity", "request_gated", None)
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.AssetOutcome("BTC", "Z", "no_opportunity", None, None)
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.InvestmentEvaluation(refused=True, refusal_reason="nope", outcomes=())
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.InvestmentEvaluation(refused=False, refusal_reason=None, outcomes=())
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.InvestmentEvaluation(
            refused=False, refusal_reason="decision_contract_invalid", outcomes=()
        )


# ------------------------------------------------------------------ G40: provenance
def test_the_marker_block_is_fixed_then_source_contracts_then_reasons_then_field_ids() -> None:
    c = _btc("candidate_unresolved").candidate
    assert c is not None
    fixed = ia.fixed_markers(ia.DETECTION_METHOD_EVALUATOR)
    ids = c.evidence_field_ids
    assert ids[: len(fixed)] == fixed
    source = ids[len(fixed) : len(fixed) + 12]
    assert source == tuple(
        f"@source.{k}={SOURCE_CONTRACTS[k]}"
        for k in (
            "unified",
            "confirmation",
            "confirmation_parameters",
            "confirmation_families",
            "opportunity",
            "opportunity_parameters",
            "ranking",
            "ranking_parameters",
            "risk_view",
            "risk",
            "risk_parameters",
            "risk_checks",
        )
    )
    rest = ids[len(fixed) + 12 :]
    assert rest[:4] == ("DI-UNRESOLVED", "DI-UNVERIFIED-CHECKS", NOT_A_THESIS, CHECKS_NOT_EVALUATED)
    assert rest[4:] == (
        "get_inst.data.BTC.s",
        "get_risk.data.BTC.u",
        "get_risk.data.BTC.p",
    )  # supporting, then findings in group order (unverified before passed)
    assert all(i.startswith("@") for i in ids[: len(fixed) + 12])
    assert not any(i.startswith("@") for i in rest)
    assert len(set(ids)) == len(ids)


def test_state_3_lists_supporting_then_contradicting_field_ids() -> None:
    c = _btc("contradicted_evidence").candidate
    assert c is not None
    plain = [i for i in c.evidence_field_ids if not i.startswith("@")]
    assert plain == ["DI-CONTRADICTED", "get_inst.data.BTC.s", "get_whale.data.BTC.c"]


def test_a_real_field_id_that_looks_like_a_marker_is_refused_for_that_asset() -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["evidence"]["supporting"][0]["field_ids"] = ["@sneaky=1"]

    assert _btc("candidate_unresolved", mutate).reason == "incomplete_decision"


@pytest.mark.parametrize("bad", ["", " x", None, 5, ["a"]])
def test_an_unclean_upstream_field_id_is_incomplete(bad: object) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["evidence"]["supporting"][0]["field_ids"] = [bad]

    assert _btc("candidate_unresolved", mutate).reason == "incomplete_decision"


def test_the_detection_method_names_the_evaluator_function() -> None:
    assert f"{ia.__name__}.{evaluate.__name__}" == ia.DETECTION_METHOD_EVALUATOR
    assert inspect.isfunction(evaluate)


# ------------------------------------------------------------------ G42: wording and determinism
def test_every_produced_string_passes_the_banned_patterns() -> None:
    for state in ALERTABLE:
        result = _run(decision(state))
        for o in result.outcomes:
            strings = [o.asset, o.state, o.outcome_class, o.reason or ""]
            if o.candidate is not None:
                c = o.candidate
                strings += [
                    c.alert_type,
                    c.severity,
                    c.dedup_key,
                    c.trigger_condition,
                    c.observed_value,
                    c.component_status,
                    c.source_tool_id,
                    *c.evidence_field_ids,
                ]
            for text in strings:
                for name, pattern in BANNED_PATTERNS.items():
                    assert not pattern.search(text), (name, text)
    for reason in (*ia.REFUSAL_REASONS, *ia.CLASS_B_REASONS, *ia.CLASS_C_REASONS):
        for pattern in BANNED_PATTERNS.values():
            assert not pattern.search(reason)


def test_identical_inputs_give_identical_results_and_do_not_mutate_the_input() -> None:
    d = decision("candidate_risk_findings_detected")
    before = copy.deepcopy(d)
    first = _run(d)
    second = _run(d)
    assert first == second
    assert d == before
    assert first.outcomes == second.outcomes


def test_the_evaluator_does_not_depend_on_the_persistence_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _run(decision("candidate_unresolved"))
    monkeypatch.setattr(ia, "INVESTMENT_ALERT_PERSISTENCE_ENABLED", True)
    assert _run(decision("candidate_unresolved")) == base


def test_the_evaluator_reads_no_clock_and_does_no_io() -> None:
    tree = ast.parse(Path(inspect.getsourcefile(ia) or "").read_text(encoding="utf-8"))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not {"now", "utcnow", "today", "time", "monotonic", "sleep"} & attrs
    assert not {"open", "print", "input", "exec", "eval", "random"} & names


# ------------------------------------------------------------------ robustness
@pytest.mark.parametrize("junk", [None, 5, "x", [], {}, [None], {"a": 1}])
def test_junk_values_in_any_asset_field_never_raise(junk: object) -> None:
    for key in ("evidence", "risk_assessment", "decision_reasons", "risk_findings", "invalidation"):
        for state in ALERTABLE:

            def mutate(d: dict[str, Any], key: str = key) -> None:
                d["assets"]["BTC"][key] = junk

            o = _btc(state, mutate)
            assert o.outcome_class in {"A", "B"}
            if o.outcome_class == "A":
                # only state 3 tolerates a junk risk block, because it does not use one
                assert state == "contradicted_evidence"
                assert key in {"risk_findings", "invalidation"}


# ------------------------------------------------------------------ real Phase 49 output
def _real(name: str) -> dict[str, Any]:
    from tests.unit.test_investment import _run as run_chain
    from tests.unit.test_risk import ALL, _violation

    if name == "unresolved":
        out = run_chain(ALL)
    elif name == "risk":
        out = run_chain(ALL, levels={"leverage": "High"})
    elif name == "gate":
        out = run_chain(ALL, mutate=_violation)
    elif name == "insufficient":
        out = run_chain(
            dict.fromkeys(("institutional", "whale", "liquidity", "macro", "market_structure"), "U")
        )
    else:
        out = run_chain({"institutional": "S", "whale": "A"})
    out["snapshot"].update({"row_id": ROW_ID, "uuid": UUID, "producer_payload_hash": PAYLOAD_HASH})
    return out


def test_real_phase_49_outputs_are_accepted_and_classified() -> None:
    unresolved = _run(_real("unresolved"))
    assert not unresolved.refused
    assert {(o.state, o.outcome_class) for o in unresolved.outcomes} == {
        ("candidate_unresolved", "A")
    }
    risk = _run(_real("risk"))
    assert {o.state for o in risk.outcomes} == {"candidate_risk_findings_detected"}
    assert risk.count("A") == 4
    gate = _run(_real("gate"))
    assert {(o.outcome_class, o.reason) for o in gate.outcomes} == {("B", "request_gated")}
    insufficient = _run(_real("insufficient"))
    assert {(o.outcome_class, o.reason) for o in insufficient.outcomes} == {
        ("C", "not_alertable_state")
    }
    contradicted = _run(_real("contradicted"))
    assert not contradicted.refused
    btc = contradicted.outcomes[0]
    assert btc.state == "contradicted_evidence"
    assert btc.outcome_class in {"A", "B"}  # A only if both sides are freshness-verified upstream
