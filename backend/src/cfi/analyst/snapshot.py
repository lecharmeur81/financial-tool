"""The immutable evidence snapshot (Phase 21, ADR-0068, ARCHITECTURE.md 5.17/5.18).

Builds the *complete* evidence Claude may use for one analysis: every one of the 14 tools
(``cfi.analyst.tools``) is called once, and every leaf value in every tool's own response is
flattened into a stable ``field_id`` (R6: "Claude may only cite numbers present in that snapshot,
each referenced by its field ID"). Nothing here computes anything new — this module only reads
already-computed, already-tested service output and re-shapes it for citation. The snapshot is
hashed (``snapshot_id``) so the same inputs always produce the same identifier, and is stored
verbatim (``ai.snapshot.payload``) before Claude is ever called, so what Claude saw is always
reproducible after the fact (ADR-0041).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from cfi.analyst import tools
from cfi.analyst.universe import KNOWN_PLATFORM_LIMITATIONS, SNAPSHOT_VERSION, TOOLS
from cfi.core.config import Settings
from cfi.core.errors import ComputationError

_NUMERIC_STRING = re.compile(r"^-?\d+(\.\d+)?$")
_MAX_STRING_FIELD_LEN = 200  # longer strings are prose/context, not a citable atomic fact


@dataclass(frozen=True, slots=True)
class SnapshotField:
    field_id: str
    display: str  # exact text Claude must copy verbatim when citing a number (R6)
    value: Decimal | None  # parsed numeric value, when the display is numeric; else None
    evidence_category: str | None = None
    quality_status: str | None = None
    unit: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class Snapshot:
    snapshot_id: str
    snapshot_version: str
    created_at: datetime
    as_of: datetime
    knowledge_time: datetime
    question: str | None
    tools_called: list[str]
    fields: list[SnapshotField]
    field_index: dict[str, SnapshotField]
    raw: dict[str, Any]
    data_quality_state: str
    has_conflicts: bool
    not_tracked: tuple[str, ...] = KNOWN_PLATFORM_LIMITATIONS

    def payload(self) -> dict[str, Any]:
        """The exact JSON stored in ``ai.snapshot.payload`` and embedded (as delimited data,
        never as instructions) in the analyst prompt."""
        return {
            "snapshot_version": self.snapshot_version,
            "as_of": self.as_of.isoformat(),
            "knowledge_time": self.knowledge_time.isoformat(),
            "question": self.question,
            "tools_called": self.tools_called,
            "not_tracked": list(self.not_tracked),
            "data_quality_state": self.data_quality_state,
            "has_conflicts": self.has_conflicts,
            "fields": {
                f.field_id: {
                    "display": f.display,
                    "evidence_category": f.evidence_category,
                    "quality_status": f.quality_status,
                    "unit": f.unit,
                    "source": f.source,
                }
                for f in self.fields
            },
            "tool_results": self.raw,
        }


def _parse_numeric(text: str) -> Decimal | None:
    if not _NUMERIC_STRING.match(text.strip()):
        return None
    try:
        return Decimal(text.strip())
    except InvalidOperation:
        return None


def _flatten(
    prefix: str, value: Any, out: list[SnapshotField], *, source_default: str | None
) -> None:
    if isinstance(value, dict):
        if "value" in value and not isinstance(value["value"], dict | list):
            # An evidence-envelope dict (DATA_DICTIONARY §2 convention): promote as one field
            # carrying its own declared metadata, rather than exploding every sub-key.
            raw_value = value.get("value")
            display = "" if raw_value is None else str(raw_value)
            out.append(
                SnapshotField(
                    field_id=prefix,
                    display=display,
                    value=_parse_numeric(display) if display else None,
                    evidence_category=value.get("evidence_category"),
                    quality_status=value.get("quality_status") or value.get("status"),
                    unit=value.get("unit"),
                    source=value.get("source") or value.get("source_provider") or source_default,
                )
            )
            return
        for key, sub in value.items():
            _flatten(f"{prefix}.{key}", sub, out, source_default=source_default)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            _flatten(f"{prefix}[{i}]", item, out, source_default=source_default)
    elif isinstance(value, bool) or value is None:
        return
    elif isinstance(value, int | float):
        display = str(value)
        out.append(SnapshotField(field_id=prefix, display=display, value=_parse_numeric(display)))
    elif isinstance(value, str):
        if not value or len(value) > _MAX_STRING_FIELD_LEN:
            return  # long prose is context, not a citable atomic fact
        out.append(SnapshotField(field_id=prefix, display=value, value=_parse_numeric(value)))


async def build_snapshot(
    engine: Any,
    settings: Settings,
    *,
    as_of: datetime,
    knowledge_time: datetime,
    question: str | None,
) -> Snapshot:
    """Call all 14 tools once and assemble the immutable snapshot. Runs every tool even for a
    narrow user question (Phase 21 foundation scope, Section 18: establish the analyst foundation;
    a later phase can add tool *selection* without changing this snapshot's shape or field IDs)."""
    results: list[tools.ToolResult] = [
        await tools.get_market_data(engine, as_of=as_of, knowledge_time=knowledge_time),
        await tools.get_institutional_flows(
            engine, settings, as_of=as_of, knowledge_time=knowledge_time
        ),
        await tools.get_whale_activity(
            engine, settings, as_of=as_of, knowledge_time=knowledge_time
        ),
        await tools.get_retail_activity(
            engine, settings, as_of=as_of, knowledge_time=knowledge_time
        ),
        await tools.get_derivatives(engine, settings, as_of=as_of, knowledge_time=knowledge_time),
        await tools.get_liquidity(engine, settings, as_of=as_of, knowledge_time=knowledge_time),
        await tools.get_macro(engine, settings, as_of=as_of, knowledge_time=knowledge_time),
        await tools.get_market_structure(
            engine, settings, as_of=as_of, knowledge_time=knowledge_time
        ),
        await tools.calculate_divergence(engine, as_of=as_of, knowledge_time=knowledge_time),
        await tools.get_market_regime(engine, as_of=as_of, knowledge_time=knowledge_time),
        await tools.find_historical_similar_periods(
            engine, as_of=as_of, knowledge_time=knowledge_time
        ),
        await tools.get_anomalies(engine, as_of=as_of, knowledge_time=knowledge_time),
        await tools.get_capital_rotation(engine, as_of=as_of, knowledge_time=knowledge_time),
    ]
    quality = tools.check_data_quality(results)
    results.append(quality)
    called_ids = {r["tool_id"] for r in results}
    declared_ids = {t.tool_id for t in TOOLS}
    if called_ids != declared_ids:
        raise ComputationError(
            "every declared tool must be called exactly once per snapshot "
            f"(missing={declared_ids - called_ids!r}, unexpected={called_ids - declared_ids!r})"
        )

    all_fields: list[SnapshotField] = []
    raw: dict[str, Any] = {}
    for r in results:
        raw[r["tool_id"]] = r
        if r["status"] == "ok" and r["data"] is not None:
            _flatten(r["tool_id"], r["data"], all_fields, source_default=r["tool_id"])

    field_index = {f.field_id: f for f in all_fields}
    quality_data = quality["data"]
    now = datetime.now(as_of.tzinfo)

    canonical = json.dumps(
        {
            "snapshot_version": SNAPSHOT_VERSION,
            "as_of": as_of.isoformat(),
            "knowledge_time": knowledge_time.isoformat(),
            "question": question,
            "raw": raw,
        },
        sort_keys=True,
        default=str,
    )
    snapshot_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    return Snapshot(
        snapshot_id=snapshot_id,
        snapshot_version=SNAPSHOT_VERSION,
        created_at=now,
        as_of=as_of,
        knowledge_time=knowledge_time,
        question=question,
        tools_called=[r["tool_id"] for r in results],
        fields=all_fields,
        field_index=field_index,
        raw=raw,
        data_quality_state=quality_data["overall_status"],
        has_conflicts=bool(quality_data["conflicting_tools"]),
    )
