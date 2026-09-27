"""Unit tests for cfi.anomaly.universe's metric registry: the 13 user-requested categories are all
present, every field required for display is populated, and — the Phase 19 instruction's explicit
constraint — no interpretation text ever labels an anomaly bullish, bearish, buy, or sell."""

from __future__ import annotations

import re

from cfi.anomaly.universe import ANOMALY_METRICS, METRICS_BY_ID, NOT_TRACKED

# The user's Phase 19 instruction, verbatim category list.
REQUESTED_CATEGORIES = (
    "ETF flows",
    "institutional flows",
    "whale flows",
    "exchange flows",
    "funding",
    "OI",
    "liquidations",
    "stablecoin supply",
    "retail activity",
    "social activity",
    "volume",
    "volatility",
    "market structure",
)

BANNED_WORDS = re.compile(
    r"\b(bullish|bearish|buy|sell|long the|short the|go long|go short)\b", re.IGNORECASE
)


def test_all_13_requested_categories_are_registered() -> None:
    categories = {d.category for d in ANOMALY_METRICS}
    assert categories == set(REQUESTED_CATEGORIES)
    assert len(ANOMALY_METRICS) == 13


def test_metric_ids_are_unique() -> None:
    ids = [d.metric_id for d in ANOMALY_METRICS]
    assert len(ids) == len(set(ids))
    assert METRICS_BY_ID.keys() == set(ids)


def test_every_metric_has_the_fields_required_for_display() -> None:
    """Metric, source, and unit must be populated for every registry entry (current value,
    percentile, magnitude, duration, timestamp and data quality are computed by the service per
    request, not stored in the registry — see cfi.anomaly.service.AnomalyService._serialize)."""
    for d in ANOMALY_METRICS:
        assert d.metric_id
        assert d.category
        assert d.label
        assert d.unit
        assert d.source
        assert d.adapter
        assert d.evidence_class in ("direct", "attributed", "inferred")
        # every band (including 'unavailable') must have at least one interpretation
        all_bands = (
            "extreme_high",
            "notable_high",
            "normal",
            "notable_low",
            "extreme_low",
            "unavailable",
        )
        for band in all_bands:
            assert band in d.interpretations
            assert len(d.interpretations[band]) >= 1


def test_no_interpretation_ever_labels_bullish_bearish_buy_or_sell() -> None:
    """The Phase 19 instruction's explicit constraint: 'Do not automatically label an anomaly
    bullish or bearish.' Enforced structurally, not just by convention."""
    offenders = []
    for d in ANOMALY_METRICS:
        for band, lines in d.interpretations.items():
            for line in lines:
                if BANNED_WORDS.search(line):
                    offenders.append((d.metric_id, band, line))
    assert offenders == []


def test_counterparts_reference_real_metric_ids() -> None:
    for d in ANOMALY_METRICS:
        for counterpart_id in d.counterparts:
            assert counterpart_id in METRICS_BY_ID, f"{d.metric_id} -> unknown {counterpart_id}"
            assert counterpart_id != d.metric_id, f"{d.metric_id} lists itself as a counterpart"


def test_not_tracked_is_a_non_empty_tuple_of_strings() -> None:
    assert isinstance(NOT_TRACKED, tuple)
    assert len(NOT_TRACKED) > 0
    assert all(isinstance(s, str) and s for s in NOT_TRACKED)
