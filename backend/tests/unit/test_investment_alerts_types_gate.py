"""Phase 51 Stage 1 — vocabulary, parameters, persistence gate, candidate (no database, no network).

Fixtures G37 (type boundary), G45 (gate), and the Stage 1 parts of G40 and G42 of
``METHODOLOGY_INVESTMENT_ALERTS.md`` (revision 6). Evaluator, planner, adapter and block tests
belong to later stages.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import subprocess
import sys
import typing
from pathlib import Path

import pytest

import cfi.alerts.investment_alerts as ia
from cfi.alerts.rules import AlertCandidate
from cfi.alerts.service import CandidateDecision
from cfi.alerts.universe import (
    ALERT_TYPE_TOOL_IDS,
    BANNED_PATTERNS,
    SEVERITY_LEVELS,
    cooldown_period,
)
from cfi.intelligence.investment import CONTRACT_VERSION
from cfi.intelligence.investment_universe import PARAMETER_VERSION, PRECEDENCE, STATES_VERSION
from cfi.realtime.events import detection_method_for

ALERTABLE = (
    "candidate_invalidation_triggered",
    "contradicted_evidence",
    "candidate_risk_findings_detected",
    "candidate_unresolved",
    "candidate_no_findings_detected",
)
NON_ALERTABLE = ("withheld_integrity_gate", "insufficient_evidence", "no_opportunity")
METHOD = ia.DETECTION_METHOD_EVALUATOR


def _candidate(**overrides: object) -> ia.InvestmentAlertCandidate:
    kwargs: dict[str, object] = {
        "asset": "BTC",
        "state": "candidate_unresolved",
        "component_status": "assessed",
        "evidence_field_ids": (*ia.fixed_markers(METHOD), "get_x.data.a", "get_y.data.b"),
        "detection_method": METHOD,
    }
    kwargs.update(overrides)
    return ia.InvestmentAlertCandidate(**kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------------ vocabulary and parameters
def test_vocabulary_partitions_the_eight_phase_49_states() -> None:
    assert ia.ALERTABLE_STATES == ALERTABLE
    assert ia.NON_ALERTABLE_STATES == NON_ALERTABLE
    assert set(ia.ALERTABLE_STATES) | set(ia.NON_ALERTABLE_STATES) == set(PRECEDENCE)
    assert not set(ia.ALERTABLE_STATES) & set(ia.NON_ALERTABLE_STATES)
    assert len(PRECEDENCE) == 8


def test_versions_and_contract_ids_match_the_existing_contracts() -> None:
    assert ia.CONTRACT_ID == CONTRACT_VERSION == "investment_decision.v0"
    assert ia.SOURCE_TOOL_ID == "investment_decision.v0"
    assert ia.PARAMETERS_VERSION == "investment_alert_params.v0"
    assert ia.METHODOLOGY_VERSION == "investment_alert_methodology.v0"
    assert ia.ALERT_TYPE == "investment_state"


def test_parameters_v0_values() -> None:
    p = ia.PARAMETERS
    assert p.version == "investment_alert_params.v0"
    assert p.cooldown_seconds == 3600
    assert p.cooldown_seconds == int(cooldown_period().total_seconds())  # alert_cooldown.v1 value
    assert p.alertable_states == ALERTABLE
    assert dict(p.severity_by_state) == dict.fromkeys(ALERTABLE, "notable")
    assert dict(ia.SEVERITY_BY_STATE) == dict.fromkeys(ALERTABLE, "notable")


def test_no_state_uses_elevated_or_critical_or_info() -> None:
    assert set(ia.SEVERITY_BY_STATE.values()) == {"notable"}
    assert set(ia.SEVERITY_BY_STATE.values()) <= set(SEVERITY_LEVELS)


def test_parameters_are_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        ia.PARAMETERS.cooldown_seconds = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    "overrides",
    [
        {"cooldown_seconds": 7200},
        {"alertable_states": ALERTABLE[:4]},
        {"severity": "elevated"},
        {"severity": "critical"},
    ],
)
def test_the_values_of_a_version_are_fixed(overrides: dict[str, object]) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.InvestmentAlertParameters(**overrides)  # type: ignore[arg-type]


def test_a_new_version_may_carry_other_values() -> None:
    p = ia.InvestmentAlertParameters(version="investment_alert_params.v1", cooldown_seconds=7200)
    assert p.cooldown_seconds == 7200


@pytest.mark.parametrize(
    "overrides",
    [
        {"cooldown_seconds": 0},
        {"cooldown_seconds": -5},
        {"cooldown_seconds": True},
        {"cooldown_seconds": "3600"},
        {"cooldown_seconds": 3600.0},
        {"alertable_states": ["contradicted_evidence"]},
        {"alertable_states": ("not_a_state",)},
        {"severity": "urgent"},
        {"severity": None},
    ],
)
def test_parameters_reject_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.InvestmentAlertParameters(version="investment_alert_params.v1", **overrides)  # type: ignore[arg-type]


# ------------------------------------------------------------------ persistence gate (G45)
def test_gate_constant_is_a_literal_false() -> None:
    assert ia.INVESTMENT_ALERT_PERSISTENCE_ENABLED is False
    assert ia.persistence_enabled() is False


@pytest.mark.parametrize(
    "value",
    [False, None, "true", "True", "1", 1, 1.0, 0, "", [], (), {}, object(), b"\x01"],
)
def test_gate_accessor_is_false_for_every_value_but_boolean_true(value: object) -> None:
    assert ia.persistence_enabled(value) is False


def test_gate_accessor_is_true_only_for_boolean_true() -> None:
    assert ia.persistence_enabled(True) is True


@pytest.mark.parametrize("corrupted", ["true", 1, None, "yes", 1.0, object()])
def test_a_corrupted_constant_fails_closed(
    monkeypatch: pytest.MonkeyPatch, corrupted: object
) -> None:
    monkeypatch.setattr(ia, "INVESTMENT_ALERT_PERSISTENCE_ENABLED", corrupted)
    assert ia.persistence_enabled() is False


def test_gate_has_no_runtime_override_path() -> None:
    """The accessor reads the module constant or one explicit argument, nothing else."""
    params = inspect.signature(ia.persistence_enabled).parameters
    assert list(params) == ["value"]
    tree = ast.parse(Path(inspect.getsourcefile(ia) or "").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    for forbidden in ("os", "environ", "getenv", "settings", "get_settings", "open", "Path"):
        assert forbidden not in names | attrs, forbidden


def test_environment_does_not_change_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "INVESTMENT_ALERT_PERSISTENCE_ENABLED",
        "CFI_INVESTMENT_ALERT_PERSISTENCE_ENABLED",
        "INVESTMENT_ALERT_PERSISTENCE",
    ):
        monkeypatch.setenv(key, "true")
    assert ia.persistence_enabled() is False


# ------------------------------------------------------------------ candidate: valid form
def test_a_valid_candidate_derives_every_row_attribute() -> None:
    c = _candidate()
    assert c.alert_type == "investment_state"
    assert c.severity == "notable"
    assert c.domain == "BTC"
    assert c.dedup_key == "investment_state:BTC"
    assert c.trigger_condition == "investment decision state for BTC"
    assert c.observed_value == "candidate_unresolved"
    assert c.reference_value is None
    assert c.source_tool_id == "investment_decision.v0"
    assert c.component_status == "assessed"
    assert c.detection_method == METHOD


@pytest.mark.parametrize("asset", ["BTC", "ETH", "SOL", "XRP"])
@pytest.mark.parametrize("state", ALERTABLE)
def test_every_scope_and_alertable_state_is_accepted(asset: str, state: str) -> None:
    c = _candidate(asset=asset, state=state)
    assert c.dedup_key == f"investment_state:{asset}"
    assert c.severity == "notable"


def test_markers_are_in_the_fixed_order_with_effective_values() -> None:
    markers = ia.fixed_markers(METHOD)
    assert markers == (
        f"@contract={CONTRACT_VERSION}",
        f"@states={STATES_VERSION}",
        f"@params={PARAMETER_VERSION}",
        "@methodology=investment_alert_methodology.v0",
        "@alert_params=investment_alert_params.v0",
        "@cooldown_seconds=3600",
        f"@detection={METHOD}",
    )
    assert all(m.startswith(ia.MARKER_PREFIX) for m in markers)


def test_extra_contract_markers_may_follow_before_plain_ids() -> None:
    ids = (*ia.fixed_markers(METHOD), "@confirmation=x.v0", "get_x.data.a")
    assert _candidate(evidence_field_ids=ids).evidence_field_ids == ids


def test_a_candidate_is_frozen_and_hashable() -> None:
    c = _candidate()
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.state = "contradicted_evidence"  # type: ignore[misc]
    assert hash(c) == hash(_candidate())


def test_identical_inputs_give_identical_candidates() -> None:
    assert _candidate() == _candidate()


def test_every_produced_string_passes_the_banned_patterns() -> None:
    for state in ALERTABLE:
        c = _candidate(state=state)
        strings = [
            c.alert_type,
            c.severity,
            c.domain,
            c.dedup_key,
            c.trigger_condition,
            c.observed_value,
            c.source_tool_id,
            c.detection_method,
            *c.evidence_field_ids,
        ]
        for text in strings:
            for name, pattern in BANNED_PATTERNS.items():
                assert not pattern.search(text), (name, text)


# ------------------------------------------------------------------ candidate: detection method
@pytest.mark.parametrize(
    "method",
    [
        "",
        " ",
        "unknown",
        METHOD.upper(),
        f" {METHOD}",
        f"{METHOD} ",
        "cfi.alerts.rules.evaluate_investment_state",  # what detection_method_for would derive
        "cfi.alerts.rules.evaluate_divergence",
        None,
        1,
        b"x",
        ["x"],
    ],
)
def test_unknown_or_invalid_detection_method_is_rejected(method: object) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        _candidate(detection_method=method)


def test_detection_method_is_required() -> None:
    with pytest.raises(TypeError):
        ia.InvestmentAlertCandidate(  # type: ignore[call-arg]
            asset="BTC",
            state="candidate_unresolved",
            component_status="assessed",
            evidence_field_ids=ia.fixed_markers(METHOD),
        )


def test_the_closed_set_holds_only_the_investment_evaluator() -> None:
    assert frozenset({METHOD}) == ia.DETECTION_METHODS
    assert METHOD == "cfi.alerts.investment_alerts.evaluate_investment_alerts"


def test_fixed_markers_reject_an_unknown_method() -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        ia.fixed_markers("anything")


def test_the_marker_for_the_detection_method_must_match_the_field() -> None:
    markers = list(ia.fixed_markers(METHOD))
    markers[-1] = "@detection=cfi.alerts.rules.evaluate_investment_state"
    with pytest.raises(ia.InvestmentAlertValidationError):
        _candidate(evidence_field_ids=tuple(markers))


# ------------------------------------------------------------------ candidate: other invalid input
@pytest.mark.parametrize("asset", ["DOGE", "btc", "BTC ", "", "GLOBAL", None, 1, ["BTC"]])
def test_unknown_assets_are_rejected(asset: object) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        _candidate(asset=asset)


@pytest.mark.parametrize("state", NON_ALERTABLE)
def test_non_alertable_states_are_rejected(state: str) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError, match="not alertable"):
        _candidate(state=state)


@pytest.mark.parametrize("state", ["not_a_state", "", "CANDIDATE_UNRESOLVED", None, 3])
def test_unknown_states_are_rejected(state: object) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        _candidate(state=state)


@pytest.mark.parametrize("status", ["", " ", " assessed", "assessed ", None, 1])
def test_component_status_must_be_a_clean_non_empty_string(status: object) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        _candidate(component_status=status)


def test_evidence_field_ids_must_start_with_the_markers_in_order() -> None:
    markers = ia.fixed_markers(METHOD)
    bad_orders: list[object] = [
        (),
        markers[:-1],
        (markers[1], markers[0], *markers[2:]),
        ("get_x.data.a", *markers),
        [*markers],  # a list, not a tuple
    ]
    for ids in bad_orders:
        with pytest.raises(ia.InvestmentAlertValidationError):
            _candidate(evidence_field_ids=ids)


def test_markers_must_precede_plain_ids() -> None:
    ids = (*ia.fixed_markers(METHOD), "get_x.data.a", "@late=marker")
    with pytest.raises(ia.InvestmentAlertValidationError, match="precede"):
        _candidate(evidence_field_ids=ids)


@pytest.mark.parametrize("entry", ["", " ", " x", "x ", None, 1])
def test_evidence_entries_must_be_clean_strings(entry: object) -> None:
    with pytest.raises(ia.InvestmentAlertValidationError):
        _candidate(evidence_field_ids=(*ia.fixed_markers(METHOD), entry))


# ------------------------------------------------------------------ type boundary (G37)
def test_the_candidate_is_not_an_alert_candidate() -> None:
    assert not issubclass(ia.InvestmentAlertCandidate, AlertCandidate)
    assert not isinstance(_candidate(), AlertCandidate)
    assert ia.InvestmentAlertCandidate.__mro__ == (ia.InvestmentAlertCandidate, object)


def test_candidate_decision_is_typed_for_alert_candidate_only() -> None:
    hints = typing.get_type_hints(CandidateDecision)
    assert hints["candidate"] is AlertCandidate


def _static_boundary(c: ia.InvestmentAlertCandidate) -> CandidateDecision:
    """Never called. The ignore below must stay *necessary*: under ``strict`` (unused ignores are
    errors) mypy fails this file if an ``InvestmentAlertCandidate`` ever becomes acceptable where
    an ``AlertCandidate`` is required. The boundary is static; Python does not check it at run
    time."""
    return CandidateDecision(
        candidate=c,  # type: ignore[arg-type]
        action="create",
        alert_id=None,
        previous_observed_value=None,
    )


def test_existing_mappings_are_unchanged_by_the_new_module() -> None:
    assert len(ALERT_TYPE_TOOL_IDS) == 11
    assert "investment_state" not in ALERT_TYPE_TOOL_IDS
    assert detection_method_for("divergence") == "cfi.alerts.rules.evaluate_divergence"


# ------------------------------------------------------------------ no I/O dependencies
ALLOWED_IMPORTS = {
    "__future__",
    "collections.abc",
    "dataclasses",
    "datetime",
    "types",
    "typing",
    "cfi.alerts.lifecycle",
    "cfi.alerts.universe",
    "cfi.decision.universe",
    "cfi.intelligence.investment_universe",
}
FORBIDDEN_ROOTS = (
    "sqlalchemy",
    "psycopg",
    "psycopg_pool",
    "asyncpg",
    "redis",
    "httpx",
    "requests",
    "aiohttp",
    "urllib3",
    "celery",
    "fastapi",
    "starlette",
    "anthropic",
    "boto3",
    "cfi.alerts.service",
    "cfi.alerts.repository",
    "cfi.db",
    "cfi.realtime",
    "cfi.worker",
    "cfi.api",
)


def _module_source() -> str:
    return Path(inspect.getsourcefile(ia) or "").read_text(encoding="utf-8")


def test_the_module_imports_only_pure_modules() -> None:
    tree = ast.parse(_module_source())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            imported.add(node.module or "")
    assert imported == ALLOWED_IMPORTS


def test_importing_the_module_loads_no_io_library() -> None:
    """Fresh interpreter: modules loaded by the new module, compared with bare ``import cfi``."""
    code = (
        "import sys\n"
        "import cfi\n"
        "before = set(sys.modules)\n"
        "import cfi.alerts.investment_alerts\n"
        "new = sorted(set(sys.modules) - before)\n"
        f"roots = {FORBIDDEN_ROOTS!r}\n"
        "bad = [m for m in new if any(m == r or m.startswith(r + '.') for r in roots)]\n"
        "print(repr(bad))\n"
    )
    env_path = ":".join(p for p in sys.path if p)
    out = subprocess.run(  # noqa: S603 — fixed interpreter, fixed code, no user input
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": env_path, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=60,
    )
    assert out.stdout.strip() == "[]", out.stdout
