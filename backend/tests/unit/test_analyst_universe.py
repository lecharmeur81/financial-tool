"""Fixed vocabulary and versioning constants (Phase 21): the section order, the tool catalog, and
the banned-language patterns that the deterministic validator enforces against live Claude output.
"""

from __future__ import annotations

from cfi.analyst.schema import AnalystResponse
from cfi.analyst.universe import (
    BANNED_PATTERNS,
    GROUNDED_LIST_SECTIONS,
    KNOWN_PLATFORM_LIMITATIONS,
    RESPONSE_SECTIONS,
    TOOLS,
    TOOLS_BY_ID,
)


def test_response_sections_match_schema_field_order() -> None:
    """Section order (R6) is enforced by construction: the schema's own field order IS the
    canonical order, so nothing can silently drift between the two."""
    assert tuple(AnalystResponse.model_fields.keys()) == RESPONSE_SECTIONS


def test_grounded_sections_are_a_subset_of_response_sections() -> None:
    assert set(GROUNDED_LIST_SECTIONS) <= set(RESPONSE_SECTIONS)


def test_fourteen_tools_declared_with_unique_ids() -> None:
    assert len(TOOLS) == 14
    assert len(TOOLS_BY_ID) == 14


def test_known_platform_limitations_are_non_empty_strings() -> None:
    assert len(KNOWN_PLATFORM_LIMITATIONS) > 0
    assert all(isinstance(line, str) and line for line in KNOWN_PLATFORM_LIMITATIONS)


def test_banned_patterns_catch_bullish_and_bearish_but_not_buy_sell_vocabulary() -> None:
    verdict = BANNED_PATTERNS["verdict_language (bullish/bearish)"]
    assert verdict.search("This looks bullish for BTC.")
    assert verdict.search("A bearish signal emerged.")
    assert not verdict.search("Aggregate buy-side flow increased.")
    assert not verdict.search("Sell-side liquidity thinned out.")


def test_banned_patterns_catch_trading_directives() -> None:
    directive = BANNED_PATTERNS["directive_language (trading instruction)"]
    assert directive.search("You should buy now.")
    assert directive.search("This is a buy signal.")
    assert not directive.search("Buyers absorbed the selling.")


def test_banned_patterns_catch_certainty_language() -> None:
    certainty = BANNED_PATTERNS["certainty_language (uncertainty presented as fact)"]
    assert certainty.search("This guarantees a rally.")
    assert certainty.search("Prices will definitely rise.")


def test_banned_patterns_catch_history_repeats_guarantee() -> None:
    history = BANNED_PATTERNS["history_guarantee_language (similarity presented as prediction)"]
    assert history.search("History always repeats itself, so this will happen again.")
