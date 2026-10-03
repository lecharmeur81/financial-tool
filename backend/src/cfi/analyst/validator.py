"""Deterministic, non-AI validation of the analyst's structured output against its own snapshot
(Phase 21 spec, Sections 4, 11, 12; ARCHITECTURE.md 5.18's "Validator checks"). Nothing here calls
Claude or any other model — every check is a plain string/number comparison against
``cfi.analyst.snapshot.Snapshot``, so it is itself fully unit-testable with synthetic fixtures.

Failure modes covered, matching the user's own Section 12 test list: an invented number (grounding),
an unsupported bullish/bearish/certainty/directive claim (language), a rotation hypothesis presented
as an observed fact (language — "capital moved" phrasing), a historical-similarity guarantee
(language), and a missing ``"Insufficient data."``/``"Sources conflict."`` disclosure when the
snapshot itself says the data called for one (Section 4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cfi.analyst.schema import AnalystResponse, EvidenceItem
from cfi.analyst.snapshot import Snapshot
from cfi.analyst.universe import (
    BANNED_PATTERNS,
    GROUNDED_LIST_SECTIONS,
    INSUFFICIENT_DATA_PHRASE,
    SOURCES_CONFLICT_PHRASE,
)

_NUMBER_TOKEN = re.compile(r"-?\d[\d,]*\.?\d*")

# Rotation/divergence must never be reported as an observed transfer between two named assets —
# structurally the same constraint ``cfi.divergence.capital_flow_map.classify_edge`` already
# enforces at the data layer (Phase 13/20); the analyst's own prose must not undo that hedge.
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
    out: set[str] = set()
    for f in fields:
        if f.value is not None:
            out.add(_normalize_number(f.display))
    return out


def _check_banned_language(text: str, where: str, errors: list[str]) -> None:
    for name, pattern in BANNED_PATTERNS.items():
        m = pattern.search(text)
        if m:
            errors.append(f"{where}: banned language [{name}] matched {m.group(0)!r} in {text!r}")
    m2 = ROTATION_FACT_LANGUAGE.search(text)
    if m2:
        errors.append(
            f"{where}: presents an inferred rotation as an observed fact ({m2.group(0)!r}) in "
            f"{text!r} — must stay a hedged hypothesis (R1, Phase 20 classify_edge discipline)"
        )


def _check_evidence_item(
    item: EvidenceItem, where: str, snapshot: Snapshot, errors: list[str]
) -> None:
    _check_banned_language(item.text, where, errors)
    for fid in item.field_ids:
        if fid not in snapshot.field_index:
            errors.append(f"{where}: cites unknown field_id {fid!r}")
    supported = _snapshot_display_numbers(snapshot, item.field_ids)
    for number in _extract_numbers(item.text):
        if number not in supported:
            errors.append(
                f"{where}: number {number!r} in {item.text!r} is not among the display values of "
                f"its cited field_ids {item.field_ids!r} (invented or ungrounded number, R6)"
            )


def _check_prose(text: str, where: str, snapshot: Snapshot, errors: list[str]) -> None:
    _check_banned_language(text, where, errors)
    all_numbers = _snapshot_display_numbers(snapshot)
    for number in _extract_numbers(text):
        if number not in all_numbers:
            errors.append(
                f"{where}: number {number!r} does not appear anywhere in the snapshot "
                "(invented or ungrounded number, R6)"
            )


def validate(response: AnalystResponse, snapshot: Snapshot) -> ValidationResult:
    errors: list[str] = []

    grounded_sections: dict[str, list[EvidenceItem]] = {
        name: getattr(response, name) for name in GROUNDED_LIST_SECTIONS
    }
    for section, items in grounded_sections.items():
        for i, item in enumerate(items):
            _check_evidence_item(item, f"{section}[{i}]", snapshot, errors)

    _check_prose(response.summary, "summary", snapshot, errors)
    _check_prose(response.market_regime, "market_regime", snapshot, errors)
    for i, text in enumerate(response.risks_uncertainties):
        _check_prose(text, f"risks_uncertainties[{i}]", snapshot, errors)
    for i, text in enumerate(response.invalidation_conditions):
        _check_prose(text, f"invalidation_conditions[{i}]", snapshot, errors)
    _check_prose(response.data_quality, "data_quality", snapshot, errors)

    for i, scenario in enumerate(response.scenarios):
        _check_banned_language(scenario.description, f"scenarios[{i}].description", errors)
        for j, item in enumerate(scenario.supporting_evidence):
            _check_evidence_item(item, f"scenarios[{i}].supporting_evidence[{j}]", snapshot, errors)
        for j, item in enumerate(scenario.contradicting_evidence):
            _check_evidence_item(
                item, f"scenarios[{i}].contradicting_evidence[{j}]", snapshot, errors
            )
        for j, text in enumerate(scenario.strengthening_conditions):
            _check_prose(text, f"scenarios[{i}].strengthening_conditions[{j}]", snapshot, errors)
        for j, text in enumerate(scenario.invalidation_conditions):
            _check_prose(text, f"scenarios[{i}].invalidation_conditions[{j}]", snapshot, errors)

    if snapshot.data_quality_state == "insufficient" and INSUFFICIENT_DATA_PHRASE not in (
        response.data_quality
    ):
        errors.append(
            "data_quality: snapshot data_quality_state is 'insufficient' but the response does "
            f"not contain the required phrase {INSUFFICIENT_DATA_PHRASE!r}"
        )
    if snapshot.has_conflicts and SOURCES_CONFLICT_PHRASE not in response.data_quality:
        errors.append(
            "data_quality: the snapshot has conflicting sources but the response does not contain "
            f"the required phrase {SOURCES_CONFLICT_PHRASE!r}"
        )

    return ValidationResult(ok=not errors, errors=errors)
