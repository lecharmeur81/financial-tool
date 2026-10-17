"""Phase 51 Stage 3 — the pure investment-alert lifecycle planner (no database, no clock).

Fixtures G01 to G08 cases (b) to (d), G09 to G25 of ``METHODOLOGY_INVESTMENT_ALERTS.md``
(revision 6), plus the gate and purity checks. Every input is hand-built: the stored-alert view is a
plain mapping of ``ExistingAlert`` values passed explicitly, and each cycle is planned separately.
There is deliberately no fake that applies a plan (that would be a test-only writer, deferred to
Phase 52), so multi-cycle scenarios restate the stored alert each cycle exactly as the later writer
would have left it (a plan never changes it). G26 concerns ``AlertService`` and belongs to Stage 6.
Nothing in this file validates persistence.
"""

from __future__ import annotations

import ast
import inspect
from datetime import timedelta
from typing import Any

import pytest

import cfi.alerts.investment_alerts as ia
from cfi.alerts.investment_alerts import evaluate_investment_alerts as evaluate
from cfi.alerts.investment_alerts import plan_investment_lifecycle as plan
from cfi.alerts.lifecycle import ExistingAlert
from tests.investment_alert_builders import NOW, SCOPES, decision, stored

COOLDOWN = ia.PARAMETERS.cooldown_seconds
ALERTABLE = ia.ALERTABLE_STATES
ALL_STATES = (*ALERTABLE, *ia.NON_ALERTABLE_STATES)
KEYS = tuple(f"investment_state:{s}" for s in SCOPES)
Existing = dict[str, ExistingAlert | None]


def _evaluation(
    states: str | dict[str, str] = "candidate_unresolved", **kw: Any
) -> ia.InvestmentEvaluation:
    result = evaluate(decision(states, **kw), stored(), now=NOW)
    assert not result.refused
    return result


def _alert(state: str, *, age: float = COOLDOWN * 10) -> ExistingAlert:
    return ExistingAlert(observed_value=state, timestamp=NOW - timedelta(seconds=age))


def _store(
    state: str | None = None, overrides: Existing | None = None, *, age: float = COOLDOWN * 10
) -> Existing:
    base: Existing = {k: (_alert(state, age=age) if state else None) for k in KEYS}
    base.update(overrides or {})
    return base


def _plan(
    evaluation: ia.InvestmentEvaluation, existing: Existing | None = None, *, enabled: bool = True
) -> ia.InvestmentLifecyclePlan:
    if enabled and existing is None:
        existing = _store()
    return plan(evaluation, existing, now=NOW, persistence=True if enabled else None)


def _dispositions(p: ia.InvestmentLifecyclePlan) -> list[str | None]:
    return [a.disposition for a in p.assets]


OTHER = {s: next(o for o in ALERTABLE if o != s) for s in ALERTABLE}


# ------------------------------------------------------------------ G01 to G08: cases (a) to (d)
@pytest.mark.parametrize("state", ALERTABLE)
def test_alertable_state_without_a_prior_alert_creates(state: str) -> None:
    p = _plan(_evaluation(state))
    assert _dispositions(p) == ["create"] * len(SCOPES)
    assert [c.observed_value for c in p.candidates_for("create")] == [state] * len(SCOPES)


@pytest.mark.parametrize("state", ALERTABLE)
@pytest.mark.parametrize("age", [1, COOLDOWN - 1, COOLDOWN, COOLDOWN * 100])
def test_alertable_state_with_the_same_prior_state_is_unchanged_at_any_age(
    state: str, age: float
) -> None:
    p = _plan(_evaluation(state), _store(state, age=age))
    assert _dispositions(p) == ["skip_unchanged"] * len(SCOPES)
    assert p.indeterminate == ()


@pytest.mark.parametrize("state", ALERTABLE)
def test_alertable_state_with_a_different_prior_state_inside_the_cooldown_is_deferred(
    state: str,
) -> None:
    p = _plan(_evaluation(state), _store(OTHER[state], age=COOLDOWN - 1))
    assert _dispositions(p) == ["skip_cooldown"] * len(SCOPES)


@pytest.mark.parametrize("state", ALERTABLE)
def test_alertable_state_with_a_different_prior_state_after_the_cooldown_rearms(
    state: str,
) -> None:
    p = _plan(_evaluation(state), _store(OTHER[state], age=COOLDOWN))
    assert _dispositions(p) == ["rearm"] * len(SCOPES)
    assert [c.observed_value for c in p.candidates_for("rearm")] == [state] * len(SCOPES)


@pytest.mark.parametrize("state", ALERTABLE)
def test_a_prior_acknowledged_alert_is_compared_like_an_active_one(state: str) -> None:
    """``ExistingAlert`` carries no status: active and acknowledged are one shape (methodology §9),
    so the plan cannot depend on acknowledgement and cannot reset it."""
    assert [f.name for f in ExistingAlert.__dataclass_fields__.values()] == [
        "observed_value",
        "timestamp",
    ]
    same = _plan(_evaluation(state), _store(state))
    other = _plan(_evaluation(state), _store(OTHER[state]))
    assert set(_dispositions(same)) == {"skip_unchanged"}
    assert set(_dispositions(other)) == {"rearm"}


@pytest.mark.parametrize("state", ia.NON_ALERTABLE_STATES)
@pytest.mark.parametrize("prior", [None, *ALERTABLE])
def test_non_alertable_states_never_act_on_any_prior_alert(state: str, prior: str | None) -> None:
    p = _plan(_evaluation(state), _store(prior))
    assert _dispositions(p) == [None] * len(SCOPES)
    assert p.candidates_for("create") == p.candidates_for("rearm") == ()


@pytest.mark.parametrize("state", ia.NON_ALERTABLE_STATES)
def test_non_alertable_states_leave_a_prior_alert_exactly_as_stored(state: str) -> None:
    existing = _store("candidate_unresolved")
    snapshot = dict(existing)
    p = _plan(_evaluation(state), existing)
    assert existing == snapshot
    assert not any(d in ("create", "rearm") for d in _dispositions(p))


def test_state_one_is_listed_indeterminate_by_both_code_paths() -> None:
    """Request-wide gate (class B ``request_gated``) and a candidate-level withheld finding."""
    existing = _store("candidate_unresolved")
    gated = _plan(_evaluation(performed=False), existing)
    assert {i.reason for i in gated.indeterminate} == {"request_gated"}
    assert {i.dedup_key for i in gated.indeterminate} == set(KEYS)

    states = {"BTC": "withheld_integrity_gate", **dict.fromkeys(SCOPES[1:], "no_opportunity")}
    withheld = _plan(_evaluation(states), existing)
    assert _dispositions(withheld)[0] is None
    assert [(i.dedup_key, i.reason) for i in withheld.indeterminate] == [
        ("investment_state:BTC", "candidate_withheld")
    ]


# ------------------------------------------------------------------ G09 to G12
def test_three_consecutive_unchanged_cycles_never_write() -> None:
    for _ in range(3):
        p = _plan(_evaluation("candidate_unresolved"), _store("candidate_unresolved"))
        assert set(_dispositions(p)) == {"skip_unchanged"}
        assert p.candidates_for("create") == p.candidates_for("rearm") == ()


def test_alertable_a_to_alertable_b_after_the_cooldown_rearms() -> None:
    p = _plan(_evaluation("candidate_risk_findings_detected"), _store("candidate_unresolved"))
    assert set(_dispositions(p)) == {"rearm"}


def test_two_assets_in_different_states_are_independent() -> None:
    states = {
        "BTC": "candidate_unresolved",
        "ETH": "no_opportunity",
        "SOL": "contradicted_evidence",
        "XRP": "withheld_integrity_gate",
    }
    existing = _store(
        None,
        {
            "investment_state:BTC": _alert("candidate_unresolved"),
            "investment_state:SOL": _alert("candidate_unresolved", age=COOLDOWN - 5),
            "investment_state:XRP": _alert("candidate_unresolved"),
        },
    )
    p = _plan(_evaluation(states), existing)
    assert dict(zip(SCOPES, _dispositions(p), strict=True)) == {
        "BTC": "skip_unchanged",
        "ETH": None,
        "SOL": "skip_cooldown",
        "XRP": None,
    }
    assert [i.dedup_key for i in p.indeterminate] == ["investment_state:XRP"]


# ------------------------------------------------------------------ G13 to G16: cooldown, re-arm
def test_deferred_state_is_compared_again_by_the_next_cycle() -> None:
    inside = _plan(_evaluation("candidate_unresolved"), _store("contradicted_evidence", age=60))
    after = _plan(
        _evaluation("candidate_unresolved"), _store("contradicted_evidence", age=COOLDOWN)
    )
    assert set(_dispositions(inside)) == {"skip_cooldown"}
    assert set(_dispositions(after)) == {"rearm"}


def test_an_intermediate_state_is_never_stored_when_the_stored_value_returns() -> None:
    stored_alert = _store("candidate_unresolved", age=600)
    during = _plan(_evaluation("contradicted_evidence"), stored_alert)
    back = _plan(_evaluation("candidate_unresolved"), stored_alert)
    assert set(_dispositions(during)) == {"skip_cooldown"}
    assert set(_dispositions(back)) == {"skip_unchanged"}
    assert during.candidates_for("create") == during.candidates_for("rearm") == ()


def test_the_cooldown_boundary_follows_decide_exactly() -> None:
    assert COOLDOWN == 3600
    at = _plan(_evaluation("contradicted_evidence"), _store("candidate_unresolved", age=COOLDOWN))
    before = _plan(
        _evaluation("contradicted_evidence"), _store("candidate_unresolved", age=COOLDOWN - 1)
    )
    assert set(_dispositions(at)) == {"rearm"}
    assert set(_dispositions(before)) == {"skip_cooldown"}


def test_the_cooldown_runs_from_the_stored_alert_not_from_the_last_evaluation() -> None:
    existing = _store("candidate_unresolved", age=COOLDOWN + 5)
    for later in (NOW, NOW + timedelta(seconds=30)):
        p = plan(_evaluation("contradicted_evidence"), existing, now=later, persistence=True)
        assert set(_dispositions(p)) == {"rearm"}
    earlier = plan(
        _evaluation("contradicted_evidence"),
        existing,
        now=NOW - timedelta(seconds=10),
        persistence=True,
    )
    assert set(_dispositions(earlier)) == {"skip_cooldown"}


def test_the_cooldown_value_is_the_approved_constant_and_not_a_parameter() -> None:
    assert ia.PARAMETERS.cooldown_seconds == 3600
    assert "cooldown" not in inspect.signature(plan).parameters


# ------------------------------------------------------------------ G17 to G25: no resolution
def test_no_disposition_resolves_expires_or_clears() -> None:
    assert ia.LIFECYCLE_ACTIONS == ("create", "skip_unchanged", "skip_cooldown", "rearm")
    assert set(ia.DISPOSITIONS) == {*ia.LIFECYCLE_ACTIONS, "not_persisted_gate_disabled"}
    for word in ("resolve", "expire", "clear", "supersede"):
        assert not any(word in d for d in ia.DISPOSITIONS)


@pytest.mark.parametrize("state", ALL_STATES)
@pytest.mark.parametrize("prior", ["candidate_unresolved", "candidate_no_findings_detected"])
def test_g17_every_state_with_a_prior_alert_only_ever_yields_the_closed_vocabulary(
    state: str, prior: str
) -> None:
    p = _plan(_evaluation(state), _store(prior))
    assert set(_dispositions(p)) <= {None, *ia.LIFECYCLE_ACTIONS}
    assert not p.refused


@pytest.mark.parametrize("reason", ["OD-UNCONFIRMED", "OD-NO-ASSET-SPECIFIC-CONFIRMER", "OD-X"])
def test_g18_no_opportunity_never_acts_whatever_its_reason(reason: str) -> None:
    def mutate(d: dict[str, Any]) -> None:
        d["assets"]["BTC"]["decision_reasons"] = [reason]

    result = evaluate(decision("no_opportunity", mutate=mutate), stored(), now=NOW)
    p = _plan(result, _store("candidate_unresolved"))
    assert set(_dispositions(p)) == {None}
    assert p.indeterminate == ()  # evaluated (class C), not unevaluable


def test_g19_a_fully_clear_no_opportunity_reading_does_not_clear_the_alert() -> None:
    """The planner has no clearance path: the section 8.4 condition is not active."""
    p = _plan(_evaluation("no_opportunity"), _store("candidate_unresolved"))
    assert set(_dispositions(p)) == {None}
    assert p.candidates_for("create") == p.candidates_for("rearm") == ()


def test_g21_insufficient_evidence_never_clears_and_the_original_state_is_unchanged() -> None:
    existing = _store("candidate_unresolved")
    assert set(_dispositions(_plan(_evaluation("insufficient_evidence"), existing))) == {None}
    assert set(_dispositions(_plan(_evaluation("candidate_unresolved"), existing))) == {
        "skip_unchanged"
    }


def test_g23_many_no_opportunity_cycles_then_the_original_state_is_unchanged() -> None:
    existing = _store("candidate_unresolved", age=COOLDOWN * 50)
    for _ in range(5):
        assert set(_dispositions(_plan(_evaluation("no_opportunity"), existing))) == {None}
    assert set(_dispositions(_plan(_evaluation("candidate_unresolved"), existing))) == {
        "skip_unchanged"
    }


def test_g24_alert_then_no_opportunity_then_another_alertable_state_rearms() -> None:
    existing = _store("candidate_unresolved", age=COOLDOWN + 1)
    assert set(_dispositions(_plan(_evaluation("no_opportunity"), existing))) == {None}
    assert set(_dispositions(_plan(_evaluation("contradicted_evidence"), existing))) == {"rearm"}


def test_g25_a_user_resolved_alert_is_not_a_stored_alert_so_the_state_creates() -> None:
    """``latest_active_for_key`` returns non-terminal alerts only; a resolved one is None."""
    p = _plan(_evaluation("candidate_unresolved"), _store(None))
    assert set(_dispositions(p)) == {"create"}


# ------------------------------------------------------------------ refusals and unevaluable data
@pytest.mark.parametrize("reason", ia.REFUSAL_REASONS)
def test_a_refused_cycle_plans_nothing_and_lists_every_stored_alert_as_indeterminate(
    reason: str,
) -> None:
    refused = ia.InvestmentEvaluation(refused=True, refusal_reason=reason, outcomes=())
    p = _plan(refused, _store("candidate_unresolved"))
    assert p.refused
    assert p.refusal_reason == reason
    assert p.assets == ()
    assert [(i.dedup_key, i.reason) for i in p.indeterminate] == [(k, reason) for k in KEYS]


def test_a_refused_cycle_without_stored_alerts_has_nothing_indeterminate() -> None:
    refused = ia.InvestmentEvaluation(
        refused=True, refusal_reason="snapshot_identity_mismatch", outcomes=()
    )
    p = _plan(refused, _store(None))
    assert p.refused
    assert p.indeterminate == ()


@pytest.mark.parametrize("reason", ia.CLASS_B_REASONS)
def test_every_class_b_reason_is_indeterminate_only_where_an_alert_is_stored(reason: str) -> None:
    outcomes = tuple(ia.AssetOutcome(s, "B", "candidate_unresolved", reason, None) for s in SCOPES)
    evaluation = ia.InvestmentEvaluation(False, None, outcomes)
    existing = _store(None, {"investment_state:ETH": _alert("candidate_unresolved")})
    p = _plan(evaluation, existing)
    assert set(_dispositions(p)) == {None}
    assert [(i.dedup_key, i.reason) for i in p.indeterminate] == [("investment_state:ETH", reason)]


def test_unevaluable_data_never_becomes_a_clear_state() -> None:
    """Across every refusal and class B reason no plan carries a create, rearm or any action."""
    refusals = [ia.InvestmentEvaluation(True, r, ()) for r in ia.REFUSAL_REASONS]
    for evaluation in refusals:
        p = _plan(evaluation, _store("candidate_unresolved"))
        assert _dispositions(p) == []
        assert p.candidates_for("create") == p.candidates_for("rearm") == ()


# ------------------------------------------------------------------ persistence gate
def test_the_production_gate_is_off_and_plans_class_a_as_not_persisted() -> None:
    p = plan(_evaluation("candidate_unresolved"), None, now=NOW)
    assert not p.persistence_enabled
    assert set(_dispositions(p)) == {"not_persisted_gate_disabled"}
    assert p.count("not_persisted_gate_disabled") == len(SCOPES)


@pytest.mark.parametrize("value", [False, None, "true", "True", 1, 1.0, [True], object()])
def test_only_the_boolean_true_enables_the_seam(value: object) -> None:
    p = plan(_evaluation("candidate_unresolved"), None, now=NOW, persistence=value)
    assert not p.persistence_enabled
    assert set(_dispositions(p)) == {"not_persisted_gate_disabled"}


def test_with_the_gate_off_decide_is_never_called_and_stored_alerts_are_never_consulted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_a: object, **_k: object) -> str:
        raise AssertionError("decide must not be called while the gate is off")

    monkeypatch.setattr(ia, "decide", boom)

    class Trap(dict):  # type: ignore[type-arg]
        def __getitem__(self, key: Any) -> Any:
            raise AssertionError("stored alerts must not be read while the gate is off")

        def get(self, *_a: Any, **_k: Any) -> Any:
            raise AssertionError("stored alerts must not be read while the gate is off")

        def __iter__(self) -> Any:
            raise AssertionError("stored alerts must not be read while the gate is off")

    for state in ALL_STATES:
        p = plan(_evaluation(state), Trap(_store("candidate_unresolved")), now=NOW)
        assert p.indeterminate == ()
        assert not any(d in ia.LIFECYCLE_ACTIONS for d in _dispositions(p))
    refused = ia.InvestmentEvaluation(True, "decision_contract_invalid", ())
    assert plan(refused, Trap(_store("candidate_unresolved")), now=NOW).indeterminate == ()


def test_the_enabled_seam_never_yields_the_gate_disabled_disposition() -> None:
    for state in ALERTABLE:
        assert "not_persisted_gate_disabled" not in _dispositions(_plan(_evaluation(state)))


def test_the_gate_constant_is_unchanged() -> None:
    assert ia.INVESTMENT_ALERT_PERSISTENCE_ENABLED is False
    assert ia.persistence_enabled() is False


# ------------------------------------------------------------------ input validation (fail closed)
def test_enabled_planning_without_the_stored_alert_view_refuses_to_guess() -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        plan(_evaluation("candidate_unresolved"), None, now=NOW, persistence=True)


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {k: None for k in KEYS[:3]},
        {**dict.fromkeys(KEYS), "investment_state:DOGE": None},
        {**dict.fromkeys(KEYS), KEYS[0]: "candidate_unresolved"},
        {
            **dict.fromkeys(KEYS),
            KEYS[0]: ExistingAlert("candidate_unresolved", NOW.replace(tzinfo=None)),
        },
        {**dict.fromkeys(KEYS), KEYS[0]: ExistingAlert("", NOW)},
        {**dict.fromkeys(KEYS), KEYS[0]: ExistingAlert(" x ", NOW)},
        [],
    ],
)
def test_a_partial_or_malformed_stored_alert_view_raises_instead_of_reading_as_no_alert(
    bad: object,
) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        plan(_evaluation("candidate_unresolved"), bad, now=NOW, persistence=True)  # type: ignore[arg-type]


def test_a_naive_now_and_a_wrong_evaluation_type_raise() -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        plan(_evaluation(), None, now=NOW.replace(tzinfo=None))
    with pytest.raises(ia.InvestmentAlertValidationError):
        plan(object(), None, now=NOW)  # type: ignore[arg-type]


def test_dedup_key_follows_the_phase_23_shape_and_rejects_unknown_assets() -> None:
    assert [ia.dedup_key_for(s) for s in SCOPES] == list(KEYS)
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.dedup_key_for("DOGE")


def test_plan_dataclasses_refuse_inconsistent_construction() -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.IndeterminateKey("investment_state:BTC", "not_a_reason")
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.IndeterminateKey("other:BTC", "request_gated")
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.AssetPlan(
            "BTC", "investment_state:ETH", "B", "candidate_unresolved", "request_gated", None, None
        )
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.AssetPlan(
            "BTC",
            "investment_state:BTC",
            "B",
            "candidate_unresolved",
            "request_gated",
            "create",
            None,
        )
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.InvestmentLifecyclePlan(True, "not_a_refusal", False, (), ())
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.InvestmentLifecyclePlan(False, None, False, (), ())


# ------------------------------------------------------------------ determinism and purity
def test_planning_is_deterministic_and_does_not_mutate_its_inputs() -> None:
    evaluation = _evaluation("candidate_unresolved")
    existing = _store("contradicted_evidence")
    before = dict(existing)
    first = _plan(evaluation, existing)
    second = _plan(evaluation, existing)
    assert first == second
    assert existing == before


def test_planner_source_has_no_clock_io_or_writer_calls() -> None:
    src = inspect.getsource(ia)
    tree = ast.parse(src)
    calls = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    assert not calls & {"now", "utcnow", "today", "time", "open", "execute", "insert_alert"}
    assert not calls & {"resolve", "supersede", "latest_active_for_key", "acknowledge"}
    assert not hasattr(ia, "InvestmentWriter")
