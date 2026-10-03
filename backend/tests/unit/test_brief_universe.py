"""`cfi.brief.universe`'s structural invariants: exactly 15 sections, every list section maps to a
real analyst tool id, and the brief's banned-language set is a strict superset of the analyst's
own (Section 7 adds position/price-target language Phase 21 never needed)."""

from __future__ import annotations

from cfi.analyst.universe import BANNED_PATTERNS as ANALYST_BANNED_PATTERNS
from cfi.analyst.universe import TOOLS_BY_ID
from cfi.brief.universe import (
    BANNED_PATTERNS,
    LIST_SECTIONS,
    MARKET_REGIME_TOOL_ID,
    RESPONSE_SECTIONS,
    SECTION_TOOL_IDS,
)


def test_response_sections_has_exactly_15_entries() -> None:
    assert len(RESPONSE_SECTIONS) == 15
    assert len(set(RESPONSE_SECTIONS)) == 15  # no duplicates


def test_every_list_section_is_declared_in_response_sections() -> None:
    assert set(LIST_SECTIONS) <= set(RESPONSE_SECTIONS)


def test_every_section_tool_id_is_a_real_analyst_tool() -> None:
    for section, tool_ids in SECTION_TOOL_IDS.items():
        assert section in LIST_SECTIONS
        for tool_id in tool_ids:
            assert tool_id in TOOLS_BY_ID, f"{section} references unknown tool {tool_id!r}"


def test_market_regime_tool_id_is_a_real_analyst_tool() -> None:
    assert MARKET_REGIME_TOOL_ID in TOOLS_BY_ID


def test_brief_banned_patterns_is_a_superset_of_the_analyst_set() -> None:
    assert set(ANALYST_BANNED_PATTERNS) <= set(BANNED_PATTERNS)
    assert len(BANNED_PATTERNS) > len(ANALYST_BANNED_PATTERNS)
