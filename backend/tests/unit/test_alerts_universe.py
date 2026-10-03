"""`cfi.alerts.universe`: the 11 alert types map to real, existing analyst tool ids; the
cooldown/severity/status vocabularies are fixed and non-empty."""

from __future__ import annotations

from datetime import timedelta

from cfi.alerts.universe import (
    ALERT_TYPE_TOOL_IDS,
    SEVERITY_LEVELS,
    STATUS_VALUES,
    cooldown_period,
)
from cfi.analyst.universe import TOOLS_BY_ID


def test_eleven_alert_types_are_declared() -> None:
    assert len(ALERT_TYPE_TOOL_IDS) == 11


def test_every_alert_type_maps_to_a_real_analyst_tool() -> None:
    for alert_type, tool_id in ALERT_TYPE_TOOL_IDS.items():
        assert tool_id in TOOLS_BY_ID, f"{alert_type} maps to unknown tool {tool_id!r}"


def test_exchange_flows_is_folded_into_whale_activity_not_a_separate_type() -> None:
    assert "exchange_flows" not in ALERT_TYPE_TOOL_IDS
    assert ALERT_TYPE_TOOL_IDS["whale_activity"] == "get_whale_activity"


def test_cooldown_period_is_positive() -> None:
    assert cooldown_period() > timedelta(0)


def test_severity_and_status_vocabularies_are_fixed() -> None:
    assert SEVERITY_LEVELS == ("info", "notable", "elevated", "critical")
    assert STATUS_VALUES == ("active", "acknowledged", "resolved", "expired")
