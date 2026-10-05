"""Decision Context (Phase 38.3): the auditable bridge between a stored platform snapshot and the
deterministic L4.5 evidence engine.

``build_decision_context(payload, scope, ...)`` hands the stored ``ai.snapshot`` payload to the
unchanged Phase 38.2 ``assess`` and wraps the ``AssessmentResult`` *as is* together with:

* the snapshot identity (four distinct identifiers, see ``cfi.decision.identity``);
* the payload's own provenance (``as_of``, ``knowledge_time``, ``snapshot_version``);
* a data-quality summary that keeps unavailable / stale / partial / not-assessed **separate**;
* the source freshness records exactly as the payload carries them;
* display strings copied verbatim from ``payload["fields"]`` for traceability (never recomputed);
* the fixed template sentences for every template id the result references.

Nothing here decides anything. The stance, confidence, posture, conflict state and CAP-U
applications are the engine's, exposed unchanged; this module never imports the rule functions and
never recalculates a score, a band or a tally. It reads no clock (``generated_at`` is
caller-supplied and excluded from equality), queries no database and calls no service,
provider or model. It does not implement ``monitor_next`` or any confirmation, weakening or
invalidation logic.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from cfi.decision.engine import assess
from cfi.decision.evidence import EvidenceReading
from cfi.decision.identity import (
    SUPPORTED_SNAPSHOT_VERSIONS,
    SnapshotIdentity,
    SnapshotRef,
    build_identity,
)
from cfi.decision.result import AssessmentResult, CapUApplication, EvidenceItem
from cfi.decision.templates import TEMPLATES
from cfi.decision.universe import (
    ASSET_SPECIFIC_DOMAINS,
    DOMAIN_TOOL,
    PARAMETERS_V0,
    SCOPE_DOMAINS,
    TOOL_DERIVATIVES,
    DecisionParameters,
    Direction,
    Freshness,
    Role,
    Stance,
    Strength,
)

__all__ = [
    "DataQualitySummary",
    "DecisionContext",
    "DecisionContextError",
    "FieldDisplay",
    "InvalidSnapshotError",
    "ReadingStatus",
    "SourceFreshness",
    "UnsupportedScopeError",
    "build_decision_context",
]

QUALITY_TOOL_ID = "check_data_quality"


class DecisionContextError(ValueError):
    """Base class for input the context layer refuses (it never refuses *missing evidence*)."""


class UnsupportedScopeError(DecisionContextError):
    """The scope is not defined by the methodology."""


class InvalidSnapshotError(DecisionContextError):
    """The payload is not a Phase 21 snapshot payload this layer can read."""


# --------------------------------------------------------------------------- value objects
@dataclass(frozen=True, slots=True)
class SourceFreshness:
    """One freshness node exactly as the payload carries it (values stringified the way the stored
    JSON holds them). ``latest`` is the source's own newest-observation time when it exposes one."""

    domain: str
    tool_id: str
    path: str  # raw payload path of the freshness node
    status: str | None
    latest: str | None
    expected_latest: str | None
    age_seconds: int | None
    rule: str | None
    note: str | None
    # True only when ``latest`` is provably later than the snapshot's ``knowledge_time``.
    after_knowledge_time: bool


@dataclass(frozen=True, slots=True)
class FieldDisplay:
    """A snapshot field's display string and metadata, copied verbatim from ``payload["fields"]``
    (display / traceability only; never recomputed)."""

    field_id: str
    display: str
    evidence_category: str | None
    quality_status: str | None
    unit: str | None
    source: str | None


@dataclass(frozen=True, slots=True)
class ReadingStatus:
    """A projection of one engine reading's status. ``status`` and ``freshness`` are the engine's
    own vocabularies, reported un-merged: ``not_assessed`` is not ``stale``."""

    domain: str
    component: str
    role: Role
    status: str
    freshness: Freshness
    quality_flags: tuple[str, ...]
    direction: Direction | None
    strength: Strength | None
    band: str | None


@dataclass(frozen=True, slots=True)
class DataQualitySummary:
    snapshot_state: str | None  # payload ``data_quality_state`` (ok / degraded / insufficient)
    source_conflicts: bool  # payload ``has_conflicts`` - tools reported conflicting data
    quality_tool_present: bool
    unavailable_tools: tuple[str, ...]  # copied from the payload's ``check_data_quality`` result
    degraded_tools: tuple[str, ...]
    conflicting_tools: tuple[str, ...]
    directional_conflict: bool  # the engine's own conflict state (independent evidence disagrees)
    readings: tuple[ReadingStatus, ...]
    # Non-context readings, grouped without merging the categories (one reading may be in several).
    unavailable_components: tuple[str, ...]
    stale_components: tuple[str, ...]
    partial_components: tuple[str, ...]
    not_assessed_components: tuple[str, ...]
    missing_domains: tuple[str, ...]  # directional domains with no reading
    missing_context: tuple[str, ...]  # regime / derivatives / volatility_anomaly not read
    not_tracked: tuple[str, ...]  # the platform's declared limitations
    look_ahead_violations: tuple[str, ...]  # paths whose time is provably after knowledge_time


# --------------------------------------------------------------------------- helpers
def _parse_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise InvalidSnapshotError(f"payload {name!r} must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InvalidSnapshotError(f"payload {name!r} is not an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise InvalidSnapshotError(f"payload {name!r} must carry a time zone")
    return parsed


def _validate_payload(payload: object) -> tuple[datetime, datetime]:
    if not isinstance(payload, dict):
        raise InvalidSnapshotError("payload must be a mapping")
    version = payload.get("snapshot_version")
    if version not in SUPPORTED_SNAPSHOT_VERSIONS:
        raise InvalidSnapshotError(
            f"unsupported snapshot_version {version!r}; supported: {SUPPORTED_SNAPSHOT_VERSIONS}"
        )
    if not isinstance(payload.get("tool_results"), dict):
        raise InvalidSnapshotError("payload 'tool_results' must be a mapping")
    return (
        _parse_timestamp(payload.get("as_of"), "as_of"),
        _parse_timestamp(payload.get("knowledge_time"), "knowledge_time"),
    )


def _text(value: object) -> str | None:
    """Stringify the way the stored JSON does (``json.dumps(default=str)``)."""
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _later_than(latest: str | None, knowledge_time: datetime) -> bool:
    """True only when ``latest`` is provably after ``knowledge_time`` (unparseable -> False)."""
    if latest is None:
        return False
    try:
        parsed = datetime.fromisoformat(latest)
    except ValueError:
        return False
    if parsed.tzinfo is None:  # a bare date (or naive time): compare calendar days only
        return parsed.date() > knowledge_time.date()
    return parsed > knowledge_time


def _freshness_record(
    domain: str, tool_id: str, path: str, node: object, knowledge_time: datetime
) -> SourceFreshness | None:
    if isinstance(node, str):
        return SourceFreshness(domain, tool_id, path, node, None, None, None, None, None, False)
    if not isinstance(node, dict):
        return None
    latest = _text(node.get("latest"))
    age = node.get("age_seconds")
    return SourceFreshness(
        domain=domain,
        tool_id=tool_id,
        path=path,
        status=_text(node.get("status")),
        latest=latest,
        expected_latest=_text(node.get("expected_latest")),
        age_seconds=age if isinstance(age, int) and not isinstance(age, bool) else None,
        rule=_text(node.get("rule")),
        note=_text(node.get("note")),
        after_knowledge_time=_later_than(latest, knowledge_time),
    )


def _tool_data(payload: dict[str, Any], tool_id: str) -> dict[str, Any] | None:
    result = payload["tool_results"].get(tool_id)
    if not isinstance(result, dict) or result.get("status") != "ok":
        return None
    data = result.get("data")
    return data if isinstance(data, dict) else None


def _source_freshness(
    payload: dict[str, Any], scope: str, knowledge_time: datetime
) -> tuple[SourceFreshness, ...]:
    out: list[SourceFreshness] = []
    for domain in SCOPE_DOMAINS[scope]:
        tool_id = DOMAIN_TOOL[domain]
        data = _tool_data(payload, tool_id)
        if data is None:
            continue
        base = f"tool_results.{tool_id}.data"
        if domain in ASSET_SPECIFIC_DOMAINS:
            assets = data.get("assets")
            for i, item in enumerate(assets if isinstance(assets, list) else []):
                if isinstance(item, dict) and item.get("asset") == scope:
                    rec = _freshness_record(
                        domain,
                        tool_id,
                        f"{base}.assets[{i}].freshness",
                        item.get("freshness"),
                        knowledge_time,
                    )
                    if rec is not None:
                        out.append(rec)
                    break
        else:
            quality = data.get("data_quality")
            sources = quality.get("sources") if isinstance(quality, dict) else None
            for j, src in enumerate(sources if isinstance(sources, list) else []):
                if isinstance(src, dict):
                    rec = _freshness_record(
                        domain,
                        tool_id,
                        f"{base}.data_quality.sources[{j}].freshness",
                        src.get("freshness"),
                        knowledge_time,
                    )
                    if rec is not None:
                        out.append(rec)
    # Derivatives: recorded only if the payload actually carries a freshness node (v0: it does not;
    # the engine then reports ``not_assessed``).
    deriv = _tool_data(payload, TOOL_DERIVATIVES)
    assets = deriv.get("assets") if deriv is not None else None
    for i, item in enumerate(assets if isinstance(assets, list) else []):
        if isinstance(item, dict) and item.get("asset") == scope and "freshness" in item:
            rec = _freshness_record(
                "derivatives",
                TOOL_DERIVATIVES,
                f"tool_results.{TOOL_DERIVATIVES}.data.assets[{i}].freshness",
                item.get("freshness"),
                knowledge_time,
            )
            if rec is not None:
                out.append(rec)
            break
    return tuple(out)


def _field_displays(
    payload: dict[str, Any], readings: tuple[EvidenceReading, ...]
) -> tuple[tuple[FieldDisplay, ...], tuple[str, ...]]:
    fields_map = payload.get("fields")
    fields_map = fields_map if isinstance(fields_map, dict) else {}
    wanted = sorted({fid for r in readings for fid in r.field_ids})
    shown: list[FieldDisplay] = []
    unresolved: list[str] = []
    for fid in wanted:
        node = fields_map.get(fid)
        if not isinstance(node, dict) or "display" not in node:
            unresolved.append(fid)
            continue
        shown.append(
            FieldDisplay(
                field_id=fid,
                display=str(node["display"]),
                evidence_category=_text(node.get("evidence_category")),
                quality_status=_text(node.get("quality_status")),
                unit=_text(node.get("unit")),
                source=_text(node.get("source")),
            )
        )
    return tuple(shown), tuple(unresolved)


def _str_tuple(value: object) -> tuple[str, ...]:
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def _data_quality(
    payload: dict[str, Any],
    result: AssessmentResult,
    source_freshness: tuple[SourceFreshness, ...],
    as_of: datetime,
    knowledge_time: datetime,
) -> DataQualitySummary:
    quality = _tool_data(payload, QUALITY_TOOL_ID)
    readings = tuple(
        ReadingStatus(
            domain=r.domain,
            component=r.component,
            role=r.role,
            status=r.status,
            freshness=r.freshness,
            quality_flags=r.quality_flags,
            direction=r.direction,
            strength=r.strength,
            band=r.band,
        )
        for r in result.readings
    )
    scored = [r for r in readings if r.role is not Role.CONTEXT]
    violations = [s.path for s in source_freshness if s.after_knowledge_time]
    if as_of > knowledge_time:
        violations.append("as_of")
    return DataQualitySummary(
        snapshot_state=result.snapshot_data_quality_state,
        source_conflicts=result.snapshot_has_conflicts,
        quality_tool_present=quality is not None,
        unavailable_tools=_str_tuple(None if quality is None else quality.get("unavailable_tools")),
        degraded_tools=_str_tuple(None if quality is None else quality.get("degraded_tools")),
        conflicting_tools=_str_tuple(None if quality is None else quality.get("conflicting_tools")),
        directional_conflict=result.conflict,
        readings=readings,
        unavailable_components=tuple(r.component for r in scored if r.status != "ok"),
        stale_components=tuple(
            r.component
            for r in scored
            if r.freshness is Freshness.STALE or "stale" in r.quality_flags
        ),
        partial_components=tuple(
            r.component
            for r in scored
            if "partial" in r.quality_flags or "flagged" in r.quality_flags
        ),
        not_assessed_components=tuple(
            r.component for r in scored if r.freshness is Freshness.NOT_ASSESSED
        ),
        missing_domains=result.missing,
        missing_context=result.missing_context,
        not_tracked=result.not_tracked,
        look_ahead_violations=tuple(violations),
    )


def _referenced_template_ids(result: AssessmentResult) -> tuple[str, ...]:
    ids: set[str] = set(result.limitations)
    ids.update(result.explanation.all_template_ids())
    for item in (*result.supportive, *result.adverse, *result.neutral):
        if item.template_id:
            ids.add(item.template_id)
    for reading in result.readings:
        if reading.template_id:
            ids.add(reading.template_id)
    for risk in result.risks:
        if risk.template_id:
            ids.add(risk.template_id)
    for cap in result.observed_caps:
        ids.add(cap.template_id)
    for applied in result.cap_u:
        ids.add(applied.template_id)
    return tuple(sorted(ids))


def _plain(obj: Any) -> Any:
    """Recursively convert to JSON-compatible plain data. Adds no meaning and drops none."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: _plain(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, enum.Enum):
        return _plain(obj.value)
    if isinstance(obj, Mapping):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, tuple | list):
        return [_plain(v) for v in obj]
    if isinstance(obj, set | frozenset):
        return sorted((_plain(v) for v in obj), key=str)
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    return obj


# --------------------------------------------------------------------------- the context
@dataclass(frozen=True, slots=True)
class DecisionContext:
    scope: str
    identity: SnapshotIdentity
    assessment: AssessmentResult  # the engine's result, unchanged
    data_quality: DataQualitySummary
    source_freshness: tuple[SourceFreshness, ...]
    field_displays: tuple[FieldDisplay, ...]
    unresolved_field_ids: tuple[str, ...]  # engine field ids with no entry in payload["fields"]
    template_text: tuple[tuple[str, str], ...]  # (template id, fixed sentence), sorted by id
    # Caller-supplied; never read from a clock here and excluded from equality.
    generated_at: datetime | None = field(default=None, compare=False)

    # -- identity / provenance (single source: ``identity``)
    @property
    def observed_at(self) -> str:
        return self.identity.as_of

    @property
    def knowledge_time(self) -> str:
        return self.identity.knowledge_time

    @property
    def snapshot_version(self) -> str:
        return self.identity.snapshot_version

    @property
    def methodology_version(self) -> str:
        return self.assessment.methodology_version

    @property
    def parameter_version(self) -> str:
        return self.assessment.parameter_version

    @property
    def template_version(self) -> str:
        return self.assessment.template_version

    # -- the engine's conclusions, exposed unchanged
    @property
    def raw_stance(self) -> Stance:
        return self.assessment.directional_stance_before_limits

    @property
    def final_stance(self) -> Stance:
        return self.assessment.final_stance

    @property
    def confidence(self) -> Any:
        return self.assessment.confidence

    @property
    def posture(self) -> Any:
        return self.assessment.posture

    @property
    def conflict(self) -> bool:
        return self.assessment.conflict

    @property
    def contradictions(self) -> tuple[str, ...]:
        return self.assessment.contradictions

    @property
    def supportive(self) -> tuple[EvidenceItem, ...]:
        return self.assessment.supportive

    @property
    def adverse(self) -> tuple[EvidenceItem, ...]:
        return self.assessment.adverse

    @property
    def neutral(self) -> tuple[EvidenceItem, ...]:
        return self.assessment.neutral

    @property
    def missing(self) -> tuple[str, ...]:
        return self.assessment.missing

    @property
    def missing_context(self) -> tuple[str, ...]:
        return self.assessment.missing_context

    @property
    def cap_u(self) -> tuple[CapUApplication, ...]:
        return self.assessment.cap_u

    @property
    def limitations(self) -> tuple[str, ...]:
        return self.assessment.limitations

    @property
    def reasons(self) -> tuple[str, ...]:
        """Every rule id that fired, in the engine's order."""
        return self.assessment.fired_rule_ids

    # -- serialisation
    def to_dict(self) -> dict[str, Any]:
        out = _plain(self)
        out["summary"] = {
            "raw_stance": _plain(self.raw_stance),
            "final_stance": _plain(self.final_stance),
            "confidence": _plain(self.confidence),
            "posture": _plain(self.posture),
            "conflict": self.conflict,
            "contradictions": list(self.contradictions),
            "missing": list(self.missing),
            "missing_context": list(self.missing_context),
            "limitations": list(self.limitations),
            "reasons": list(self.reasons),
            "cap_u_rule_ids": [c.rule_id for c in self.cap_u],
        }
        return out  # type: ignore[no-any-return]

    def deterministic_dict(self) -> dict[str, Any]:
        """``to_dict`` without ``generated_at`` - the part that is a pure function of the inputs."""
        out = self.to_dict()
        out.pop("generated_at", None)
        return out


def build_decision_context(
    payload: dict[str, Any],
    scope: str,
    *,
    snapshot_ref: SnapshotRef | None = None,
    generated_at: datetime | None = None,
    parameters: DecisionParameters = PARAMETERS_V0,
) -> DecisionContext:
    """Assess one scope of one stored snapshot payload and wrap the result.

    Raises ``UnsupportedScopeError`` for an undefined scope and ``InvalidSnapshotError`` for a
    payload that is not a supported Phase 21 snapshot. Missing or unavailable *evidence* never
    raises: it is the engine's first-class, explained state."""
    if scope not in SCOPE_DOMAINS:
        raise UnsupportedScopeError(
            f"scope {scope!r} is not defined; defined: {sorted(SCOPE_DOMAINS)}"
        )
    as_of, knowledge_time = _validate_payload(payload)
    result = assess(payload, scope, parameters)
    identity = build_identity(payload, snapshot_ref)
    freshness = _source_freshness(payload, scope, knowledge_time)
    displays, unresolved = _field_displays(payload, result.readings)
    return DecisionContext(
        scope=scope,
        identity=identity,
        assessment=result,
        data_quality=_data_quality(payload, result, freshness, as_of, knowledge_time),
        source_freshness=freshness,
        field_displays=displays,
        unresolved_field_ids=unresolved,
        template_text=tuple(
            (tid, TEMPLATES[tid]) for tid in _referenced_template_ids(result) if tid in TEMPLATES
        ),
        generated_at=generated_at,
    )
