"""Capital Rotation Engine calculated metrics (L2/L3) — pure functions, no I/O (Phase 20).

Every input is a normalized, already point-in-time-filtered ``cfi.divergence.metrics.Series``
(built by ``cfi.divergence.adapters.Adapters``). This module adds exactly two things beyond what
``cfi.divergence.metrics`` and ``cfi.divergence.capital_flow_map`` already provide (R13: reuse
before reinventing):

- **``share_series``**: turns two raw value series (e.g. one asset's market cap, and the genuine
  global TOTAL crypto market cap) into a single market-share-percent series, so
  ``cfi.divergence.metrics.window_reading``/``rolling_series`` (both reused unchanged) can classify
  its own direction, magnitude, percentile and duration exactly as they already do for every other
  Divergence Engine comparison.
- **``flow_corroboration``**: the check the user explicitly asked for — "provide the evidence
  supporting each inferred rotation." ``cfi.divergence.capital_flow_map.classify_edge`` already
  never claims capital moved from A to B, only that the two nodes' *shares* moved in opposite
  directions ("consistent with, but not proof of"). This function additionally checks whether
  OBSERVED FLOW data (institutional ETF net flow, whale exchange net flow) for the same node moved
  the *same* direction as its own share (corroborating) or the opposite direction (contradicting).
  It is still not proof of a rotation — flow direction and share direction can each have other
  causes — but it is a second, independent, already-observed data point the hypothesis can be
  checked against, exactly as R1 asks ("provide the evidence").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from cfi.divergence.metrics import Direction, Series, SeriesPoint, WindowReading


@dataclass(frozen=True, slots=True)
class _ValuedPoint:
    time: datetime
    value: Decimal


def _asof(points: Series, at: datetime) -> _ValuedPoint | None:
    """The latest valued point at or before ``at``, or ``None`` if none exists — never a future
    point, never an interpolation (R3)."""
    candidates = [p for p in points if p.has_value and p.time <= at]
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.time)
    if latest.value is None:  # pragma: no cover - guarded by has_value above
        return None
    return _ValuedPoint(latest.time, latest.value)


def sum_series(components: list[Series]) -> Series:
    """Element-wise sum of several raw value series (e.g. several assets' own market caps, to
    build the "large_caps" aggregate), as-of joined on the union of every component's own valued
    timestamps — each component's last known reading is carried forward to a timestamp it did not
    itself report (never an interpolation, R3). A timestamp for which even one component has no
    as-of reading yet contributes ``value=None`` rather than silently treating the missing
    component as zero, which would understate the true combined total."""
    all_times = sorted({p.time for s in components for p in s if p.value is not None})
    out: Series = []
    for t in all_times:
        parts: list[Decimal] = []
        complete = True
        for s in components:
            found = _asof(s, t)
            if found is None:
                complete = False
                break
            parts.append(found.value)
        if not complete:
            out.append(SeriesPoint(t, None, "insufficient_data"))
        else:
            out.append(SeriesPoint(t, sum(parts, start=Decimal(0)), "ok"))
    return out


def share_series(numerator: Series, denominator: Series) -> Series:
    """``numerator`` expressed as a percent of ``denominator``, at each of the numerator's own
    valued points. The denominator is looked up "as-of" that same point in time (carrying its
    last known reading forward — the same point-in-time philosophy used everywhere else in this
    platform, never an interpolation, R3). A point whose denominator is unavailable or exactly
    zero at that time is emitted with ``value=None`` (``quality_status='insufficient_data'``)
    rather than silently dropped, so downstream window/rolling calculations see a real gap, never
    a shortened series that hides it."""
    out: Series = []
    for p in numerator:
        if p.value is None:
            out.append(p)
            continue
        denom = _asof(denominator, p.time)
        if denom is None or denom.value == 0:
            out.append(SeriesPoint(p.time, None, "insufficient_data"))
            continue
        out.append(SeriesPoint(p.time, (p.value / denom.value) * 100, p.quality_status))
    return out


@dataclass(frozen=True, slots=True)
class FlowCheck:
    status: str  # checked / not_applicable / insufficient_flow_data
    supporting: list[str]
    contradicting: list[str]


def flow_corroboration(
    node_label: str,
    share_direction: Direction,
    *,
    institutional_reading: WindowReading | None,
    whale_reading: WindowReading | None,
) -> FlowCheck:
    """Compares ``node_label``'s own market-share direction against its OBSERVED institutional
    ETF and/or whale exchange net-flow direction over the same window. Deterministic and
    rule-based (L3 Statistical Signal, not an AI interpretation, R2/R6): every bullet cites a
    direction already computed by ``cfi.divergence.metrics.window_reading``, nothing here is a
    free-text judgment call. Never claims the flow *caused* the share move — only whether the two
    already-observed readings point the same way."""
    if institutional_reading is None and whale_reading is None:
        return FlowCheck("not_applicable", [], [])
    if share_direction == "unavailable":
        return FlowCheck("not_applicable", [], [])
    supporting: list[str] = []
    contradicting: list[str] = []
    for flow_label, reading in (
        ("institutional ETF", institutional_reading),
        ("whale exchange", whale_reading),
    ):
        if reading is None or reading.status != "ok" or reading.direction == "unavailable":
            continue
        flow_dir = reading.direction
        if flow_dir == share_direction:
            supporting.append(
                f"{node_label}'s {flow_label} net flow was also '{flow_dir}' over the same "
                "window — OBSERVED FLOW data is directionally consistent with the share move "
                "(still not proof that this flow caused the share change)."
            )
        elif flow_dir != "flat" and share_direction != "flat":
            contradicting.append(
                f"{node_label}'s {flow_label} net flow was '{flow_dir}' while its market share "
                f"moved '{share_direction}' over the same window — the share move is not "
                "corroborated by this OBSERVED FLOW data."
            )
    if not supporting and not contradicting:
        return FlowCheck("insufficient_flow_data", [], [])
    return FlowCheck("checked", supporting, contradicting)


__all__ = ["FlowCheck", "flow_corroboration", "share_series", "sum_series"]
