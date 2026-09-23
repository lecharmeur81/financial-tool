"""US trading calendar against the NYSE's published holiday list."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from cfi.core.calendars import (
    is_us_trading_day,
    new_york_time,
    next_us_trading_day,
    nyse_holidays,
    previous_us_trading_day,
    us_trading_days,
)

# Full-day closures as published at https://www.nyse.com/markets/hours-calendars (read 2026-09-24).
NYSE_PUBLISHED = {
    2026: [
        date(2026, 1, 1),
        date(2026, 1, 19),
        date(2026, 2, 16),
        date(2026, 4, 3),
        date(2026, 5, 25),
        date(2026, 6, 19),
        date(2026, 7, 3),
        date(2026, 9, 7),
        date(2026, 11, 26),
        date(2026, 12, 25),
    ],
    2027: [
        date(2027, 1, 1),
        date(2027, 1, 18),
        date(2027, 2, 15),
        date(2027, 3, 26),
        date(2027, 5, 31),
        date(2027, 6, 18),
        date(2027, 7, 5),
        date(2027, 9, 6),
        date(2027, 11, 25),
        date(2027, 12, 24),
    ],
    # 1 January 2028 is a Saturday: "no New Year's Day holiday is observed".
    2028: [
        date(2028, 1, 17),
        date(2028, 2, 21),
        date(2028, 4, 14),
        date(2028, 5, 29),
        date(2028, 6, 19),
        date(2028, 7, 4),
        date(2028, 9, 4),
        date(2028, 11, 23),
        date(2028, 12, 25),
    ],
}


@pytest.mark.parametrize("year", sorted(NYSE_PUBLISHED))
def test_rule_based_holidays_match_the_published_nyse_calendar(year: int) -> None:
    assert sorted(nyse_holidays(year)) == NYSE_PUBLISHED[year]


def test_special_closure_is_not_a_trading_day() -> None:
    assert not is_us_trading_day(date(2025, 1, 9))  # National Day of Mourning
    assert is_us_trading_day(date(2025, 1, 10))


def test_weekends_and_holidays_are_skipped() -> None:
    # Friday 2026-09-04 → Labor Day Monday 2026-09-07 is closed → Tuesday 2026-09-08
    assert next_us_trading_day(date(2026, 9, 4)) == date(2026, 9, 8)
    assert previous_us_trading_day(date(2026, 9, 8)) == date(2026, 9, 4)
    assert us_trading_days(date(2026, 9, 4), date(2026, 9, 10)) == [
        date(2026, 9, 4),
        date(2026, 9, 8),
        date(2026, 9, 9),
    ]


def test_new_york_time_handles_daylight_saving() -> None:
    assert new_york_time(date(2026, 7, 1), time(18)) == datetime(2026, 7, 1, 22, tzinfo=UTC)
    assert new_york_time(date(2026, 12, 1), time(18)) == datetime(2026, 12, 1, 23, tzinfo=UTC)
