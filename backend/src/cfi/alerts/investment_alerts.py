"""Investment-alert vocabulary, parameters, persistence gate, candidate and evaluator (Phase 51).

Specification: ``METHODOLOGY_INVESTMENT_ALERTS.md`` revision 6 and ADR-0087 (Proposed).
**Experimental and not validated against historical outcomes** (Phase 50 is a required future
phase). Nothing here is a signal, a recommendation, a probability or a safety rating: a candidate
records that an asset's Phase 49 decision state *was observed* in one snapshot.

This module is **pure**: no database, repository, network, file, environment or settings access,
and no import of ``cfi.alerts.service``, ``cfi.alerts.repository`` or ``cfi.realtime``. It holds
the closed vocabulary, the versioned parameters, the persistence gate, the validated
candidate (Stage 1), the pure evaluator (Stage 2) and the pure lifecycle planner (Stage 3). The
adapter and the cycle block come in later, separately reviewed stages. The planner reuses
``cfi.alerts.lifecycle.decide`` unchanged (a pure, database-free module) and adds no writer.

Persistence gate (M-1, K-4). Investment-alert persistence is DISABLED in Phase 51.
``INVESTMENT_ALERT_PERSISTENCE_ENABLED`` is a hard-coded ``False``. It has no environment,
configuration, database, request or runtime override. ``persistence_enabled`` is the single
accessor: it returns true only for the boolean ``True``; any other value (absent, ``None``, a
string, a number) means disabled. Changing the constant is a code change that is not permitted
until Phase 52 is implemented, its prerequisites (methodology §18.1) are reviewed, the
schema-verification procedure is separately approved and passed, and the user approves the change
in writing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

from cfi.alerts.lifecycle import Candidate, ExistingAlert, decide
from cfi.alerts.universe import SEVERITY_LEVELS
from cfi.decision.universe import SCOPE_DOMAINS
from cfi.intelligence.investment_universe import PARAMETER_VERSION as INVESTMENT_PARAMETER_VERSION
from cfi.intelligence.investment_universe import PRECEDENCE, STATES_VERSION

__all__ = [
    "ADAPTER_REFUSAL_REASONS",
    "ALERTABLE_STATES",
    "ALERT_TYPE",
    "CLASS_B_REASONS",
    "CLASS_C_REASONS",
    "CONTRACT_ID",
    "DETECTION_METHODS",
    "DETECTION_METHOD_EVALUATOR",
    "DISPOSITIONS",
    "EVALUATOR_REFUSAL_REASONS",
    "GATE_DISABLED_DISPOSITION",
    "INDETERMINATE_REASONS",
    "INVESTMENT_ALERT_PERSISTENCE_ENABLED",
    "LIFECYCLE_ACTIONS",
    "MARKER_PREFIX",
    "METHODOLOGY_VERSION",
    "NON_ALERTABLE_STATES",
    "OUTCOME_CLASSES",
    "PARAMETERS",
    "PARAMETERS_VERSION",
    "REFUSAL_REASONS",
    "SEVERITY_BY_STATE",
    "SOURCE_TOOL_ID",
    "AssetOutcome",
    "AssetPlan",
    "IndeterminateKey",
    "InvestmentAlertCandidate",
    "InvestmentAlertParameters",
    "InvestmentAlertValidationError",
    "InvestmentEvaluation",
    "InvestmentLifecyclePlan",
    "StoredSnapshotIdentity",
    "dedup_key_for",
    "evaluate_investment_alerts",
    "fixed_markers",
    "persistence_enabled",
    "plan_investment_lifecycle",
]

METHODOLOGY_VERSION: Final = "investment_alert_methodology.v0"
PARAMETERS_VERSION: Final = "investment_alert_params.v0"

# The Phase 49 contract this layer reads. Also the alert row's ``source_tool_id``: a contract id,
# not an analyst tool (methodology §10).
CONTRACT_ID: Final = "investment_decision.v0"
SOURCE_TOOL_ID: Final = CONTRACT_ID

# Free text in ``usr.alert_event`` (no CHECK); deliberately NOT added to ``ALERT_TYPE_TOOL_IDS``.
ALERT_TYPE: Final = "investment_state"
_TRIGGER_TEMPLATE: Final = "investment decision state for {asset}"

# --------------------------------------------------------------------------- persistence gate
# Hard-coded. No environment, configuration, database, request or runtime override (K-4).
INVESTMENT_ALERT_PERSISTENCE_ENABLED: Final = False


class _Absent:
    """Sentinel type: 'no value was supplied'. Never equal to ``True``."""

    __slots__ = ()


_ABSENT: Final = _Absent()


def persistence_enabled(value: object = _ABSENT) -> bool:
    """The single accessor of the persistence gate. Fail-closed.

    True only for the boolean ``True``. ``None``, ``"true"``, ``1``, ``1.0``, any other object and
    an absent value all mean disabled. With no argument the module constant is read (and is
    ``False``). The optional argument exists only so a later stage can pass an explicit test value
    through the same check; it is not a configuration path and nothing in production supplies it.
    """
    candidate = INVESTMENT_ALERT_PERSISTENCE_ENABLED if isinstance(value, _Absent) else value
    return candidate is True


# --------------------------------------------------------------------------- vocabulary
# The eight closed Phase 49 states (``investment_states.v0``), in Phase 49 precedence order. This
# layer adds no state and no state text.
_STATE_IDS: Final[tuple[str, ...]] = tuple(PRECEDENCE)

# Provisional (A-4): five alertable states at uniform ``notable``. Each was verified against the
# Phase 49 classifier (methodology §6.1). Order follows Phase 49 precedence.
ALERTABLE_STATES: Final[tuple[str, ...]] = (
    "candidate_invalidation_triggered",
    "contradicted_evidence",
    "candidate_risk_findings_detected",
    "candidate_unresolved",
    "candidate_no_findings_detected",
)
NON_ALERTABLE_STATES: Final[tuple[str, ...]] = tuple(
    s for s in _STATE_IDS if s not in ALERTABLE_STATES
)

# ``notable`` is Phase 23's uniform default. ``elevated`` would make an alert eligible for the
# Phase 35 AI trigger and ``critical`` has no basis (methodology §6), so neither is used.
SEVERITY_BY_STATE: Final = MappingProxyType(dict.fromkeys(ALERTABLE_STATES, "notable"))

# --------------------------------------------------------------------------- detection method
# A closed set containing only the investment evaluator (A-2). The final function name is fixed when
# the evaluator is written (Stage 2); the value is validated here and never derived from the alert
# type string (``detection_method_for`` would otherwise name a function that does not exist).
DETECTION_METHOD_EVALUATOR: Final = "cfi.alerts.investment_alerts.evaluate_investment_alerts"
DETECTION_METHODS: Final = frozenset({DETECTION_METHOD_EVALUATOR})

# Provenance markers are ``evidence_field_ids`` entries in a reserved namespace: each begins with
# this prefix, which no real field id does (real field ids begin with a tool id).
MARKER_PREFIX: Final = "@"


class InvestmentAlertValidationError(ValueError):
    """An investment-alert value or candidate violates the specification (never repaired)."""


# Run-time type tests take ``object`` so that the checks stay meaningful for values that bypass the
# static types (the dataclasses do not check field types at run time).
def _not_str(value: object) -> bool:
    return not isinstance(value, str)


def _not_clean_str(value: object) -> bool:
    return not isinstance(value, str) or not value or value != value.strip()


def _not_plain_int(value: object) -> bool:
    return isinstance(value, bool) or not isinstance(value, int)


def _not_tuple(value: object) -> bool:
    return not isinstance(value, tuple)


# --------------------------------------------------------------------------- parameters
_V0_COOLDOWN_SECONDS: Final = 3600  # the ``alert_cooldown.v1`` value; not data-derived (A-8)


@dataclass(frozen=True, slots=True)
class InvestmentAlertParameters:
    """``investment_alert_params.v0``: declared, experimental, not fitted, not validated.

    A parameter change creates a new version string; the values of an existing version are fixed,
    so constructing the v0 object with any other value raises, not a mislabelled object.
    """

    version: str = PARAMETERS_VERSION
    cooldown_seconds: int = _V0_COOLDOWN_SECONDS
    alertable_states: tuple[str, ...] = ALERTABLE_STATES
    severity: str = "notable"

    def __post_init__(self) -> None:
        if _not_plain_int(self.cooldown_seconds):
            raise InvestmentAlertValidationError("cooldown_seconds must be an int")
        if self.cooldown_seconds <= 0:
            raise InvestmentAlertValidationError("cooldown_seconds must be positive")
        if _not_tuple(self.alertable_states):
            raise InvestmentAlertValidationError("alertable_states must be a tuple")
        unknown = [s for s in self.alertable_states if s not in _STATE_IDS]
        if unknown:
            raise InvestmentAlertValidationError(f"unknown decision states: {unknown}")
        if _not_str(self.severity) or self.severity not in SEVERITY_LEVELS:
            raise InvestmentAlertValidationError(f"unknown severity: {self.severity!r}")
        if self.version == PARAMETERS_VERSION and (
            self.cooldown_seconds != _V0_COOLDOWN_SECONDS
            or self.alertable_states != ALERTABLE_STATES
            or self.severity != "notable"
        ):
            raise InvestmentAlertValidationError(
                f"the values of {PARAMETERS_VERSION} are fixed; a change needs a new version"
            )

    @property
    def severity_by_state(self) -> MappingProxyType[str, str]:
        return MappingProxyType(dict.fromkeys(self.alertable_states, self.severity))


PARAMETERS: Final = InvestmentAlertParameters()


# --------------------------------------------------------------------------- provenance markers
def _check_detection_method(value: object) -> None:
    if not isinstance(value, str) or value not in DETECTION_METHODS:
        raise InvestmentAlertValidationError(
            f"detection_method {value!r} is not in the closed set {sorted(DETECTION_METHODS)}"
        )


def fixed_markers(detection_method: str) -> tuple[str, ...]:
    """The fixed-order marker block every investment alert starts with (methodology §10).

    The Phase 44 to 48 contract and parameter markers of the decision's ``source_contracts`` may
    follow, still ``@``-prefixed; they are added by the evaluator in a later stage.
    """
    _check_detection_method(detection_method)
    return (
        f"{MARKER_PREFIX}contract={CONTRACT_ID}",
        f"{MARKER_PREFIX}states={STATES_VERSION}",
        f"{MARKER_PREFIX}params={INVESTMENT_PARAMETER_VERSION}",
        f"{MARKER_PREFIX}methodology={METHODOLOGY_VERSION}",
        f"{MARKER_PREFIX}alert_params={PARAMETERS_VERSION}",
        f"{MARKER_PREFIX}cooldown_seconds={PARAMETERS.cooldown_seconds}",
        f"{MARKER_PREFIX}detection={detection_method}",
    )


# --------------------------------------------------------------------------- candidate
@dataclass(frozen=True, slots=True)
class InvestmentAlertCandidate:
    """One investment alert the evaluator would raise. A distinct type, not an ``AlertCandidate``.

    It is deliberately **not** a subclass of ``cfi.alerts.rules.AlertCandidate``, so it cannot be
    placed in a ``cfi.alerts.service.CandidateDecision`` (whose ``candidate`` field is typed
    ``AlertCandidate``) without a type error. That boundary is enforced statically (mypy); Python
    does not check dataclass field types at run time. The Phase 35 isolation therefore also rests
    on investment outcomes never entering ``EvaluationResult.decisions`` (methodology §11).

    Only the variable facts are fields; every other attribute of the would-be alert row is derived
    and cannot be set inconsistently. ``detection_method`` is required and validated against a
    closed set; it is never derived from the alert type string.
    """

    asset: str
    state: str
    component_status: str
    evidence_field_ids: tuple[str, ...]
    detection_method: str

    def __post_init__(self) -> None:
        _check_detection_method(self.detection_method)
        if _not_str(self.asset) or self.asset not in SCOPE_DOMAINS:
            raise InvestmentAlertValidationError(
                f"asset {self.asset!r} is not a Phase 49 scope {sorted(SCOPE_DOMAINS)}"
            )
        if _not_str(self.state) or self.state not in _STATE_IDS:
            raise InvestmentAlertValidationError(f"unknown decision state: {self.state!r}")
        if self.state not in ALERTABLE_STATES:
            raise InvestmentAlertValidationError(f"decision state {self.state!r} is not alertable")
        if _not_clean_str(self.component_status):
            raise InvestmentAlertValidationError("component_status must be a clean non-empty str")
        self._check_evidence_field_ids()

    def _check_evidence_field_ids(self) -> None:
        ids = self.evidence_field_ids
        if _not_tuple(ids):
            raise InvestmentAlertValidationError("evidence_field_ids must be a tuple")
        if any(_not_clean_str(i) for i in ids):
            raise InvestmentAlertValidationError("evidence_field_ids entries must be clean strings")
        expected = fixed_markers(self.detection_method)
        if ids[: len(expected)] != expected:
            raise InvestmentAlertValidationError(
                "evidence_field_ids must start with the fixed provenance markers, in order"
            )
        seen_plain = False
        for entry in ids[len(expected) :]:
            if entry.startswith(MARKER_PREFIX):
                if seen_plain:
                    raise InvestmentAlertValidationError(
                        "provenance markers must precede all other evidence_field_ids"
                    )
            else:
                seen_plain = True

    # ---- derived attributes of the would-be ``usr.alert_event`` row (methodology §10)
    @property
    def alert_type(self) -> str:
        return ALERT_TYPE

    @property
    def severity(self) -> str:
        return SEVERITY_BY_STATE[self.state]

    @property
    def domain(self) -> str:
        return self.asset

    @property
    def dedup_key(self) -> str:
        return f"{ALERT_TYPE}:{self.asset}"

    @property
    def trigger_condition(self) -> str:
        return _TRIGGER_TEMPLATE.format(asset=self.asset)

    @property
    def observed_value(self) -> str:
        return self.state

    @property
    def reference_value(self) -> None:
        return None

    @property
    def source_tool_id(self) -> str:
        return SOURCE_TOOL_ID


# =========================================================================== Stage 2: evaluator
# Pure: reads one ``investment_decision.v0`` mapping plus the identity and times of the stored
# snapshot row the caller read, and returns one outcome per Phase 49 scope. It reads no clock
# (``now`` is passed in), no repository and no network, and it never mutates its input.
#
# Evidence freshness (methodology §5): the only authority is the upstream per-source ``fresh``
# status, surfaced by Phase 49 as ``freshness_verified`` on each evidence reference. No age
# threshold exists here, and ``now``, ``as_of`` and ``knowledge_time`` are never evidence
# freshness: they are used only to refuse an impossible time context.

# Closed reasons. Cycle-level refusals leave every existing alert untouched (methodology §5.4).
# The evaluator emits the first four; the adapter (``investment_adapter``, Stage 5) emits the other
# three before any decision exists. They are kept separately identifiable and unioned here so the
# evaluation, planner and indeterminate-reason contracts stay one closed vocabulary.
EVALUATOR_REFUSAL_REASONS: Final[tuple[str, ...]] = (
    "decision_contract_invalid",
    "snapshot_time_invalid",
    "snapshot_time_in_future",
    "snapshot_identity_mismatch",
)
ADAPTER_REFUSAL_REASONS: Final[tuple[str, ...]] = (
    "snapshot_not_found",
    "snapshot_row_invalid",
    "decision_inputs_refused",
)
REFUSAL_REASONS: Final[tuple[str, ...]] = (*EVALUATOR_REFUSAL_REASONS, *ADAPTER_REFUSAL_REASONS)
# Class B (not evaluable or withheld) and class C (evaluated, not alertable); methodology §8.2.
CLASS_B_REASONS: Final[tuple[str, ...]] = (
    "request_gated",
    "candidate_withheld",
    "incomplete_decision",
    "evidence_freshness_unverified",
)
CLASS_C_REASONS: Final[tuple[str, ...]] = ("not_alertable_state",)
OUTCOME_CLASSES: Final[tuple[str, ...]] = ("A", "B", "C")

_SCOPES: Final[tuple[str, ...]] = tuple(SCOPE_DOMAINS)
_WITHHELD_STATE: Final = "withheld_integrity_gate"
_CLASS_C_STATES: Final = frozenset({"insufficient_evidence", "no_opportunity"})
_CANDIDATE_STATES: Final = frozenset(
    {
        "candidate_invalidation_triggered",
        "candidate_risk_findings_detected",
        "candidate_unresolved",
        "candidate_no_findings_detected",
    }
)
_NOT_A_THESIS: Final = "DI-CANDIDATE-IS-NOT-A-THESIS"
_CHECKS_NOT_EVALUATED: Final = "DI-DECLARED-CHECKS-NOT-EVALUATED"
_FINDING_GROUPS: Final = (
    "detected",
    "unverified",
    "unavailable",
    "not_applicable",
    "withheld",
    "passed",
)
# ``source_contracts`` keys of ``investment_decision.v0`` (Phase 44 to 48 contract and parameter
# versions), in the order their markers are written.
_SOURCE_CONTRACT_KEYS: Final = (
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


@dataclass(frozen=True, slots=True)
class StoredSnapshotIdentity:
    """What the caller read from the stored snapshot row (never derived from the decision)."""

    row_id: int
    uuid: str
    payload_hash: str
    as_of: datetime
    knowledge_time: datetime


@dataclass(frozen=True, slots=True)
class AssetOutcome:
    """One asset's outcome in one cycle. Exactly one class; every class is recorded."""

    asset: str
    outcome_class: str
    state: str
    reason: str | None
    candidate: InvestmentAlertCandidate | None

    def __post_init__(self) -> None:
        if self.asset not in _SCOPES or self.state not in _STATE_IDS:
            raise InvestmentAlertValidationError("outcome asset or state is not in the vocabulary")
        if self.outcome_class == "A":
            if self.reason is not None or self.candidate is None:
                raise InvestmentAlertValidationError("class A has a candidate and no reason")
            if self.candidate.asset != self.asset or self.candidate.state != self.state:
                raise InvestmentAlertValidationError("class A candidate does not match its outcome")
        elif self.outcome_class == "B":
            if self.reason not in CLASS_B_REASONS or self.candidate is not None:
                raise InvestmentAlertValidationError("class B has a closed reason and no candidate")
        elif self.outcome_class == "C":
            if self.reason not in CLASS_C_REASONS or self.candidate is not None:
                raise InvestmentAlertValidationError("class C has a closed reason and no candidate")
        else:
            raise InvestmentAlertValidationError(f"unknown outcome class: {self.outcome_class!r}")


@dataclass(frozen=True, slots=True)
class InvestmentEvaluation:
    """The result of one evaluation: a cycle-level refusal, or one outcome per scope in order."""

    refused: bool
    refusal_reason: str | None
    outcomes: tuple[AssetOutcome, ...]

    def __post_init__(self) -> None:
        if self.refused:
            if self.refusal_reason not in REFUSAL_REASONS or self.outcomes:
                raise InvestmentAlertValidationError(
                    "a refusal has a closed reason and no outcomes"
                )
        else:
            if self.refusal_reason is not None:
                raise InvestmentAlertValidationError("only a refusal carries a refusal reason")
            if tuple(o.asset for o in self.outcomes) != _SCOPES:
                raise InvestmentAlertValidationError("one outcome per scope, in scope order")

    @property
    def candidates(self) -> tuple[InvestmentAlertCandidate, ...]:
        return tuple(o.candidate for o in self.outcomes if o.candidate is not None)

    def count(self, outcome_class: str) -> int:
        return sum(1 for o in self.outcomes if o.outcome_class == outcome_class)


def _refuse(reason: str) -> InvestmentEvaluation:
    return InvestmentEvaluation(refused=True, refusal_reason=reason, outcomes=())


def _mapping(value: object) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _aware(value: object) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def _clean_str_list(value: object) -> list[str] | None:
    if not isinstance(value, list):
        return None
    if any(_not_clean_str(x) for x in value):
        return None
    return list(value)


def _all_verified(refs: object) -> bool:
    """Fail-closed: a non-empty list whose every reference has ``freshness_verified`` ``True``."""
    if not isinstance(refs, list) or not refs:
        return False
    return all(isinstance(r, Mapping) and r.get("freshness_verified") is True for r in refs)


def _field_ids(refs: object, into: list[str]) -> bool:
    """Append the upstream field ids of references. False if any entry is not a clean string."""
    if not isinstance(refs, list):
        return False
    for ref in refs:
        ids = _clean_str_list(ref.get("field_ids", []) if isinstance(ref, Mapping) else None)
        if ids is None:
            return False
        into.extend(ids)
    return True


def _source_markers(decision: Mapping[str, Any]) -> tuple[str, ...] | None:
    sources = _mapping(decision.get("source_contracts"))
    if sources is None:
        return None
    markers: list[str] = []
    for key in _SOURCE_CONTRACT_KEYS:
        value = sources.get(key)
        if _not_clean_str(value):
            return None
        markers.append(f"{MARKER_PREFIX}source.{key}={value}")
    return tuple(markers)


def _validate_decision(
    decision: object,
) -> tuple[Mapping[str, Any], tuple[str, ...]] | None:
    d = _mapping(decision)
    if d is None or d.get("contract_version") != CONTRACT_ID:
        return None
    params = _mapping(d.get("parameters"))
    if (
        params is None
        or params.get("version") != INVESTMENT_PARAMETER_VERSION
        or params.get("states_version") != STATES_VERSION
    ):
        return None
    assessment = _mapping(d.get("assessment"))
    if assessment is None or not isinstance(assessment.get("performed"), bool):
        return None
    source = _source_markers(d)
    if _mapping(d.get("snapshot")) is None or source is None:
        return None
    assets = _mapping(d.get("assets"))
    if assets is None or set(assets) != set(_SCOPES):
        return None
    for block in assets.values():
        b = _mapping(block)
        if b is None or not isinstance(b.get("decision_state"), str):
            return None
        if b["decision_state"] not in _STATE_IDS:
            return None
    if not assessment["performed"] and any(
        assets[s]["decision_state"] != _WITHHELD_STATE for s in _SCOPES
    ):
        return None  # a gated request withholds every asset; anything else is inconsistent
    return d, source


def _identity_matches(decision: Mapping[str, Any], stored: StoredSnapshotIdentity) -> bool:
    snap = _mapping(decision.get("snapshot"))
    if snap is None:
        return False
    row_id = snap.get("row_id")
    uuid = snap.get("uuid")
    payload_hash = snap.get("producer_payload_hash")
    # Validate both sides before comparing: equal-but-invalid values (None == None,
    # "" == "", True == 1) must never count as a matching identity.
    if (
        _not_plain_int(stored.row_id)
        or _not_clean_str(stored.uuid)
        or _not_clean_str(stored.payload_hash)
        or _not_plain_int(row_id)
        or _not_clean_str(uuid)
        or _not_clean_str(payload_hash)
    ):
        return False
    return row_id == stored.row_id and uuid == stored.uuid and payload_hash == stored.payload_hash


def _not_identity(value: object) -> bool:
    return not isinstance(value, StoredSnapshotIdentity)


def _check_times(stored: StoredSnapshotIdentity, now: datetime) -> str | None:
    if not (_aware(now) and _aware(stored.as_of) and _aware(stored.knowledge_time)):
        return "snapshot_time_invalid"
    if stored.as_of > now or stored.knowledge_time > now:
        return "snapshot_time_in_future"
    return None


def _outcome_b(asset: str, state: str, reason: str) -> AssetOutcome:
    return AssetOutcome(asset, "B", state, reason, None)


def _risk_blocks_well_formed(
    state: str, findings: Mapping[str, Any] | None, invalidation: Mapping[str, Any] | None
) -> bool:
    """A candidate state needs the Phase 48 blocks in the shape Phase 49 emits (fail closed)."""
    if findings is None or invalidation is None:
        return False
    if any(not isinstance(findings.get(group), list) for group in _FINDING_GROUPS):
        return False
    summary = invalidation.get("summary")
    if not isinstance(summary, str) or not isinstance(invalidation.get("conditions"), list):
        return False
    # "triggered" is the first test of the Phase 49 classifier, so it holds for state 2 only.
    return (summary == "triggered") == (state == "candidate_invalidation_triggered")


def _evaluate_asset(
    asset: str, block: Mapping[str, Any], *, markers: tuple[str, ...]
) -> AssetOutcome:
    state: str = block["decision_state"]
    if state == _WITHHELD_STATE:
        return _outcome_b(asset, state, "candidate_withheld")
    if state in _CLASS_C_STATES:
        return AssetOutcome(asset, "C", state, "not_alertable_state", None)

    incomplete = _outcome_b(asset, state, "incomplete_decision")
    unverified = _outcome_b(asset, state, "evidence_freshness_unverified")

    status = _mapping(block.get("risk_assessment"))
    evidence = _mapping(block.get("evidence"))
    reasons = _clean_str_list(block.get("decision_reasons"))
    if status is None or evidence is None or not reasons:  # Phase 49 always gives a reason
        return incomplete
    component = status.get("state")
    if not isinstance(component, str) or _not_clean_str(component):
        return incomplete
    findings = _mapping(block.get("risk_findings"))
    if state in _CANDIDATE_STATES and not _risk_blocks_well_formed(
        state, findings, _mapping(block.get("invalidation"))
    ):
        return incomplete
    if state in {"candidate_unresolved", "candidate_no_findings_detected"} and not (
        _NOT_A_THESIS in reasons and _CHECKS_NOT_EVALUATED in reasons
    ):
        return incomplete

    # Freshness guard (methodology §5.3): fail closed, no age threshold, missing is never neutral.
    needed = ["supporting"] + (["contradicting"] if state == "contradicted_evidence" else [])
    if any(not isinstance(evidence.get(group), list) for group in needed):
        return incomplete
    if not all(_all_verified(evidence[group]) for group in needed):
        return unverified

    plain: list[str] = list(reasons)
    for group in needed:
        if not _field_ids(evidence[group], plain):
            return incomplete
    if findings is not None:
        for group in _FINDING_GROUPS:
            if not _field_ids(findings.get(group), plain):
                return incomplete
    unique = tuple(dict.fromkeys(plain))
    if any(entry.startswith(MARKER_PREFIX) for entry in unique):
        return incomplete  # a real id may never look like a provenance marker
    try:
        candidate = InvestmentAlertCandidate(
            asset=asset,
            state=state,
            component_status=component,
            evidence_field_ids=(*markers, *unique),
            detection_method=DETECTION_METHOD_EVALUATOR,
        )
    except InvestmentAlertValidationError:
        return incomplete
    return AssetOutcome(asset, "A", state, None, candidate)


def evaluate_investment_alerts(
    decision: object, stored: StoredSnapshotIdentity, *, now: datetime
) -> InvestmentEvaluation:
    """Evaluate one ``investment_decision.v0`` for alert candidates. Pure and deterministic.

    Never raises for bad data: an unusable decision, time context or identity is a cycle-level
    refusal (nothing is created, re-armed or cleared); an asset that cannot be evaluated is class B;
    an evaluated, non-alertable asset is class C; an eligible alertable asset is class A with a
    validated candidate. A state change is never a recommendation and nothing here ranks states.
    """
    validated = _validate_decision(decision)
    if validated is None:
        return _refuse("decision_contract_invalid")
    d, source = validated
    if _not_identity(stored):
        return _refuse("snapshot_identity_mismatch")
    time_problem = _check_times(stored, now)
    if time_problem is not None:
        return _refuse(time_problem)
    if not _identity_matches(d, stored):
        return _refuse("snapshot_identity_mismatch")

    markers = (*fixed_markers(DETECTION_METHOD_EVALUATOR), *source)
    assets = d["assets"]
    performed: bool = d["assessment"]["performed"]
    outcomes = tuple(
        _outcome_b(scope, assets[scope]["decision_state"], "request_gated")
        if not performed
        else _evaluate_asset(scope, assets[scope], markers=markers)
        for scope in _SCOPES
    )
    return InvestmentEvaluation(refused=False, refusal_reason=None, outcomes=outcomes)


# =========================================================================== Stage 3: planner
# Pure: turns one ``InvestmentEvaluation`` plus the caller-supplied most recent non-terminal stored
# alert per dedup key into a plan of dispositions. It reads no clock (``now`` is passed in), no
# repository, no network and no file, and it writes nothing: a plan is data, never an action taken.
#
# The lifecycle vocabulary is the existing Phase 23 one, reused unchanged: ``decide`` returns
# ``create``, ``skip_unchanged``, ``skip_cooldown`` or ``rearm``. This layer adds no lifecycle
# state, no timing threshold and no transition rule. In particular there is no ``resolve`` and no
# ``expire`` disposition (methodology §8.1): ``expired`` appears only as the Phase 23 consequence
# of a ``rearm``, which the later (Phase 52) writer would perform.
#
# While the persistence gate is off (methodology §4.1) no stored investment alert is read, none is
# consulted here, ``decide`` is not called, and an alertable asset is planned as
# ``not_persisted_gate_disabled``: deduplication, cooldown and re-arm are specified and tested on
# fakes, and operative only when a test (later, Phase 52) injects the enabled seam.

LIFECYCLE_ACTIONS: Final[tuple[str, ...]] = ("create", "skip_unchanged", "skip_cooldown", "rearm")
GATE_DISABLED_DISPOSITION: Final = "not_persisted_gate_disabled"
DISPOSITIONS: Final[tuple[str, ...]] = (*LIFECYCLE_ACTIONS, GATE_DISABLED_DISPOSITION)
# Why a stored alert's condition could not currently be evaluated: a class B reason or a refusal.
INDETERMINATE_REASONS: Final[tuple[str, ...]] = (*CLASS_B_REASONS, *REFUSAL_REASONS)


def dedup_key_for(asset: str) -> str:
    """The Phase 23 dedup key shape ``{alert_type}:{asset}`` for one Phase 49 scope."""
    if _not_str(asset) or asset not in _SCOPES:
        raise InvestmentAlertValidationError(f"asset {asset!r} is not a Phase 49 scope")
    return f"{ALERT_TYPE}:{asset}"


_DEDUP_KEYS: Final[tuple[str, ...]] = tuple(dedup_key_for(s) for s in _SCOPES)


@dataclass(frozen=True, slots=True)
class AssetPlan:
    """One asset's planned disposition. Class B and C carry no disposition: nothing happens."""

    asset: str
    dedup_key: str
    outcome_class: str
    state: str
    reason: str | None
    disposition: str | None
    candidate: InvestmentAlertCandidate | None

    def __post_init__(self) -> None:
        if self.dedup_key != dedup_key_for(self.asset):
            raise InvestmentAlertValidationError("dedup_key does not match the asset")
        if self.outcome_class == "A":
            if self.disposition not in DISPOSITIONS or self.candidate is None:
                raise InvestmentAlertValidationError("class A has a disposition and a candidate")
        elif self.outcome_class in ("B", "C"):
            if self.disposition is not None or self.candidate is not None:
                raise InvestmentAlertValidationError("class B and C have no disposition")
        else:
            raise InvestmentAlertValidationError(f"unknown outcome class: {self.outcome_class!r}")


@dataclass(frozen=True, slots=True)
class IndeterminateKey:
    """A stored alert left exactly as stored because its condition cannot currently be evaluated."""

    dedup_key: str
    reason: str

    def __post_init__(self) -> None:
        if self.dedup_key not in _DEDUP_KEYS or self.reason not in INDETERMINATE_REASONS:
            raise InvestmentAlertValidationError("indeterminate key or reason is not closed")


@dataclass(frozen=True, slots=True)
class InvestmentLifecyclePlan:
    """The plan for one cycle: a refusal, or one ``AssetPlan`` per scope in scope order."""

    refused: bool
    refusal_reason: str | None
    persistence_enabled: bool
    assets: tuple[AssetPlan, ...]
    indeterminate: tuple[IndeterminateKey, ...]

    def __post_init__(self) -> None:
        if self.refused:
            if self.refusal_reason not in REFUSAL_REASONS or self.assets:
                raise InvestmentAlertValidationError("a refusal has a closed reason and no assets")
        else:
            if self.refusal_reason is not None:
                raise InvestmentAlertValidationError("only a refusal carries a refusal reason")
            if tuple(a.asset for a in self.assets) != _SCOPES:
                raise InvestmentAlertValidationError("one plan per scope, in scope order")
        gated_off = [a for a in self.assets if a.disposition == GATE_DISABLED_DISPOSITION]
        if self.persistence_enabled and gated_off:
            raise InvestmentAlertValidationError("gate-disabled disposition while enabled")
        if not self.persistence_enabled and (
            self.indeterminate
            or any(a.outcome_class == "A" and a not in gated_off for a in self.assets)
        ):
            raise InvestmentAlertValidationError("a gated-off plan consults no stored alert")

    def count(self, disposition: str) -> int:
        return sum(1 for a in self.assets if a.disposition == disposition)

    def candidates_for(self, disposition: str) -> tuple[InvestmentAlertCandidate, ...]:
        """Candidates a later writer would have to act on for one disposition (data only)."""
        return tuple(
            a.candidate for a in self.assets if a.disposition == disposition and a.candidate
        )


def _checked_existing(existing: object) -> dict[str, ExistingAlert | None]:
    """The caller's stored-alert view: exactly the four dedup keys, each an alert or ``None``.

    An absent or partial view is never read as 'no alert' (that would create duplicates), so it
    raises: it is a caller error, not data.
    """
    if not isinstance(existing, Mapping) or set(existing) != set(_DEDUP_KEYS):
        raise InvestmentAlertValidationError(
            f"existing alerts must map exactly the dedup keys {list(_DEDUP_KEYS)}"
        )
    out: dict[str, ExistingAlert | None] = {}
    for key in _DEDUP_KEYS:
        alert = existing[key]
        if alert is not None and (
            not isinstance(alert, ExistingAlert)
            or _not_clean_str(alert.observed_value)
            or not _aware(alert.timestamp)
        ):
            raise InvestmentAlertValidationError(f"existing alert for {key} is not usable")
        out[key] = alert
    return out


def plan_investment_lifecycle(
    evaluation: InvestmentEvaluation,
    existing: Mapping[str, ExistingAlert | None] | None = None,
    *,
    now: datetime,
    persistence: object = _ABSENT,
) -> InvestmentLifecyclePlan:
    """Plan the lifecycle disposition of one evaluation. Pure and deterministic.

    ``existing`` maps each dedup key to the most recent non-terminal stored alert (acknowledged
    alerts are compared like active ones) or ``None``; it is required, and consulted, only when
    persistence is enabled. ``persistence`` is the test seam of methodology §4.1: absent means the
    hard-coded gate, which is off; only the boolean ``True`` enables.

    Only a class A asset is ever planned through ``decide``. A refused cycle and class B and C
    assets leave every stored alert exactly as stored; a stored alert that cannot currently be
    evaluated is listed in ``indeterminate``. Nothing here resolves, expires or clears an alert.
    """
    if not isinstance(evaluation, InvestmentEvaluation):
        raise InvestmentAlertValidationError("evaluation must be an InvestmentEvaluation")
    if not _aware(now):
        raise InvestmentAlertValidationError("now must be a timezone-aware datetime")
    enabled = persistence_enabled(persistence)
    stored_alerts = _checked_existing(existing) if enabled else {}

    def stored_for(key: str) -> ExistingAlert | None:
        return stored_alerts.get(key)

    if evaluation.refused:
        reason = evaluation.refusal_reason
        indeterminate = tuple(
            IndeterminateKey(key, str(reason))
            for key in _DEDUP_KEYS
            if enabled and stored_for(key) is not None
        )
        return InvestmentLifecyclePlan(True, reason, enabled, (), indeterminate)

    plans: list[AssetPlan] = []
    indeterminate_keys: list[IndeterminateKey] = []
    for outcome in evaluation.outcomes:
        key = dedup_key_for(outcome.asset)
        disposition: str | None = None
        if outcome.candidate is not None:
            if not enabled:
                disposition = GATE_DISABLED_DISPOSITION
            else:
                disposition = decide(
                    stored_for(key),
                    Candidate(observed_value=outcome.candidate.observed_value),
                    now=now,
                    cooldown_seconds=PARAMETERS.cooldown_seconds,
                )
        elif outcome.outcome_class == "B" and enabled and stored_for(key) is not None:
            indeterminate_keys.append(IndeterminateKey(key, str(outcome.reason)))
        plans.append(
            AssetPlan(
                asset=outcome.asset,
                dedup_key=key,
                outcome_class=outcome.outcome_class,
                state=outcome.state,
                reason=outcome.reason,
                disposition=disposition,
                candidate=outcome.candidate,
            )
        )
    return InvestmentLifecyclePlan(False, None, enabled, tuple(plans), tuple(indeterminate_keys))
