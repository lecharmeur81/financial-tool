"""Deterministic, non-AI validation of the Daily Brief against its own snapshot and
``cfi.brief.changes.ChangeSet`` (Phase 22 spec, Sections 5-7, 10). Nothing here calls Claude or any
other model — every check is a plain string/number comparison, the same discipline
``cfi.analyst.validator`` already applies to ``AnalystResponse`` (this module does not modify or
import from that one's private helpers; it is a small, independent set of checks over this phase's
own 15-section, change-aware response shape).

Failure modes covered, matching the spec's own Section 11 test list: an invented number
(grounding), a banned directive/certainty/position-sizing/price-target phrase (Section 7), a
rotation hypothesis presented as an observed fact, a claimed change with no defined comparison
basis or an unknown ``change_id`` (Section 5), and a missing ``"Insufficient data."``/``"Sources
conflict."`` disclosure when the snapshot's own computed state calls for one (Section 6).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cfi.analyst.snapshot import Snapshot
from cfi.brief.changes import ChangeSet
from cfi.brief.schema import BriefEvidenceItem, BriefResponse
from cfi.brief.universe import (
    BANNED_PATTERNS,
    INSUFFICIENT_DATA_PHRASE,
    LIST_SECTIONS,
    MARKET_REGIME_TOOL_ID,
    SECTION_TOOL_IDS,
    SOURCES_CONFLICT_PHRASE,
)

_NUMBER_TOKEN = re.compile(r"-?\d[\d,]*\.?\d*")
_FIELD_ID_TOOL_PREFIX = re.compile(r"[.\[]")

# Rotation/divergence must never be reported as an observed transfer between two named assets —
# the same hedge ``cfi.analyst.validator.ROTATION_FACT_LANGUAGE`` already enforces for the Phase 21
# analyst (R1); the brief's own "Capital Rotation" section must not undo it either.
ROTATION_FACT_LANGUAGE = re.compile(
    r"\bcapital (?:has )?moved from\b|\bmoved capital from\b|\bshifted capital from\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)


def _normalize_number(token: str) -> str:
    return token.replace(",", "").rstrip(".")


def _extract_numbers(text: str) -> set[str]:
    return {_normalize_number(m.group(0)) for m in _NUMBER_TOKEN.finditer(text)}


def _snapshot_display_numbers(snapshot: Snapshot, field_ids: list[str] | None = None) -> set[str]:
    fields = (
        snapshot.fields
        if field_ids is None
        else [snapshot.field_index[fid] for fid in field_ids if fid in snapshot.field_index]
    )
    return {_normalize_number(f.display) for f in fields if f.value is not None}


def _field_id_tool(field_id: str) -> str:
    return _FIELD_ID_TOOL_PREFIX.split(field_id, maxsplit=1)[0]


def _check_banned_language(text: str, where: str, errors: list[str]) -> None:
    for name, pattern in BANNED_PATTERNS.items():
        m = pattern.search(text)
        if m:
            errors.append(f"{where}: banned language [{name}] matched {m.group(0)!r} in {text!r}")
    m2 = ROTATION_FACT_LANGUAGE.search(text)
    if m2:
        errors.append(
            f"{where}: presents an inferred rotation as an observed fact ({m2.group(0)!r}) in "
            f"{text!r} — must stay a hedged hypothesis (R1)"
        )


def _check_item(
    item: BriefEvidenceItem,
    where: str,
    snapshot: Snapshot,
    changes: ChangeSet,
    allowed_tool_ids: tuple[str, ...],
    errors: list[str],
) -> None:
    _check_banned_language(item.text, where, errors)

    for fid in item.field_ids:
        if fid not in snapshot.field_index:
            errors.append(f"{where}: cites unknown field_id {fid!r}")
        elif _field_id_tool(fid) not in allowed_tool_ids:
            errors.append(
                f"{where}: cites field_id {fid!r} from tool {_field_id_tool(fid)!r}, which is "
                f"outside this section's own domain tool(s) {allowed_tool_ids!r} (ADR-0069 "
                "discipline: a section's evidence may only cite its own domain's tool)"
            )

    supported = _snapshot_display_numbers(snapshot, item.field_ids)
    for number in _extract_numbers(item.text):
        if number not in supported:
            errors.append(
                f"{where}: number {number!r} in {item.text!r} is not among the display values of "
                f"its cited field_ids {item.field_ids!r} (invented or ungrounded number, R6)"
            )

    for cid in item.change_ids:
        if changes.comparison_basis == "none":
            errors.append(
                f"{where}: cites change_id {cid!r}, but there is no previous brief to compare "
                "against (comparison_basis='none') — no meaningful change can be claimed without "
                "a defined comparison basis (Section 5)"
            )
        elif not changes.is_valid_change_id(cid):
            errors.append(f"{where}: cites unknown change_id {cid!r}")


def validate(response: BriefResponse, snapshot: Snapshot, changes: ChangeSet) -> ValidationResult:
    errors: list[str] = []

    for section in LIST_SECTIONS:
        items: list[BriefEvidenceItem] = getattr(response, section)
        allowed = SECTION_TOOL_IDS[section]
        for i, item in enumerate(items):
            _check_item(item, f"{section}[{i}]", snapshot, changes, allowed, errors)

    regime = response.market_regime
    for i, item in enumerate(regime.evidence):
        _check_item(
            item,
            f"market_regime.evidence[{i}]",
            snapshot,
            changes,
            (MARKET_REGIME_TOOL_ID,),
            errors,
        )
    for i, item in enumerate(regime.changed_since_previous):
        _check_item(
            item,
            f"market_regime.changed_since_previous[{i}]",
            snapshot,
            changes,
            (MARKET_REGIME_TOOL_ID,),
            errors,
        )
    if changes.comparison_basis == "none" and regime.changed_since_previous:
        errors.append(
            "market_regime.changed_since_previous: no previous brief exists "
            "(comparison_basis='none') but this list is non-empty — nothing can yet be called a "
            "change versus the previous period (Section 5)"
        )
    _check_banned_language(regime.current, "market_regime.current", errors)
    _check_banned_language(regime.confidence, "market_regime.confidence", errors)

    _check_banned_language(response.executive_summary, "executive_summary", errors)
    all_numbers = _snapshot_display_numbers(snapshot)
    for number in _extract_numbers(response.executive_summary):
        if number not in all_numbers:
            errors.append(
                f"executive_summary: number {number!r} does not appear anywhere in the snapshot "
                "(invented or ungrounded number, R6)"
            )

    _check_banned_language(response.data_quality, "data_quality", errors)
    for i, text in enumerate(response.risks_uncertainties):
        _check_banned_language(text, f"risks_uncertainties[{i}]", errors)
    for i, text in enumerate(response.what_to_monitor):
        _check_banned_language(text, f"what_to_monitor[{i}]", errors)

    if snapshot.data_quality_state == "insufficient" and INSUFFICIENT_DATA_PHRASE not in (
        response.data_quality
    ):
        errors.append(
            "data_quality: snapshot data_quality_state is 'insufficient' but the response does "
            f"not contain the required phrase {INSUFFICIENT_DATA_PHRASE!r}"
        )
    if snapshot.has_conflicts and SOURCES_CONFLICT_PHRASE not in response.data_quality:
        errors.append(
            "data_quality: the snapshot has conflicting sources but the response does not "
            f"contain the required phrase {SOURCES_CONFLICT_PHRASE!r}"
        )

    return ValidationResult(ok=not errors, errors=errors)
