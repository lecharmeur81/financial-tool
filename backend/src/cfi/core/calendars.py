"""Trading calendars (ADR-0039).

US-listed products (spot crypto ETFs) report per **US trading date**, not per UTC crypto day.
This module knows which dates the New York Stock Exchange is open, so the system can tell a
non-trading day (no data expected) from a missing trading day (a data gap).

Rules (NYSE full-day holidays, verified 2026-09-24 against https://www.nyse.com/markets/hours-calendars
for 2026–2028):

- New Year's Day (1 Jan; Sunday → Monday 2 Jan; Saturday → **not** observed);
- Martin Luther King Jr. Day (3rd Monday of January);
- Washington's Birthday (3rd Monday of February);
- Good Friday (two days before Easter Sunday);
- Memorial Day (last Monday of May);
- Juneteenth (19 June, from 2022; Saturday → Friday, Sunday → Monday);
- Independence Day (4 July; Saturday → Friday, Sunday → Monday);
- Labor Day (1st Monday of September);
- Thanksgiving Day (4th Thursday of November);
- Christmas Day (25 December; Saturday → Friday, Sunday → Monday).

Unscheduled closures cannot be derived from rules and are listed explicitly
(``SPECIAL_CLOSURES``). Early closes (1:00 p.m.) are still trading days. The calendar is used from
2024 onward (the first US spot bitcoin ETFs began trading on 11 January 2024).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
CALENDAR_START = date(2024, 1, 1)

# Unscheduled full-day NYSE closures (not derivable from rules).
SPECIAL_CLOSURES: dict[date, str] = {
    date(2025, 1, 9): "National Day of Mourning for former President Jimmy Carter",
}


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The ``n``-th ``weekday`` (Mon=0) of a month; ``n = -1`` means the last one."""
    if n > 0:
        first = date(year, month, 1)
        offset = (weekday - first.weekday()) % 7
        return first + timedelta(days=offset + 7 * (n - 1))
    last = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous Gregorian algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month, day = divmod(h + l_ - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _observed(day: date) -> date:
    """Saturday holidays move to Friday, Sunday holidays to Monday."""
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


@lru_cache(maxsize=64)
def nyse_holidays(year: int) -> dict[date, str]:
    """Full-day NYSE closures in ``year`` (rule-based holidays plus special closures)."""
    holidays: dict[date, str] = {}
    new_year = date(year, 1, 1)
    if new_year.weekday() == 6:
        holidays[new_year + timedelta(days=1)] = "New Year's Day (observed)"
    elif new_year.weekday() != 5:  # Saturday: not observed (NYSE rule)
        holidays[new_year] = "New Year's Day"
    holidays[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    holidays[_nth_weekday(year, 2, 0, 3)] = "Washington's Birthday"
    holidays[_easter(year) - timedelta(days=2)] = "Good Friday"
    holidays[_nth_weekday(year, 5, 0, -1)] = "Memorial Day"
    if year >= 2022:
        holidays[_observed(date(year, 6, 19))] = "Juneteenth National Independence Day"
    holidays[_observed(date(year, 7, 4))] = "Independence Day"
    holidays[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    holidays[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving Day"
    holidays[_observed(date(year, 12, 25))] = "Christmas Day"
    for day, reason in SPECIAL_CLOSURES.items():
        if day.year == year:
            holidays[day] = reason
    return holidays


def is_us_trading_day(day: date) -> bool:
    return day.weekday() < 5 and day not in nyse_holidays(day.year)


def us_trading_days(start: date, end: date) -> list[date]:
    """US trading dates in the half-open range [start, end)."""
    return [d for d in _dates(start, end) if is_us_trading_day(d)]


def next_us_trading_day(day: date) -> date:
    candidate = day + timedelta(days=1)
    while not is_us_trading_day(candidate):
        candidate += timedelta(days=1)
    return candidate


def previous_us_trading_day(day: date) -> date:
    candidate = day - timedelta(days=1)
    while not is_us_trading_day(candidate):
        candidate -= timedelta(days=1)
    return candidate


def new_york_time(day: date, at: time) -> datetime:
    """``day`` at local New York wall-clock time ``at``, in UTC (daylight saving handled)."""
    return datetime.combine(day, at, tzinfo=NEW_YORK).astimezone(UTC)


def date_label(day: date) -> datetime:
    """The storage label of a calendar date: 00:00 UTC on that date."""
    return datetime.combine(day, time(0), tzinfo=UTC)


def _dates(start: date, end: date) -> Iterator[date]:
    day = start
    while day < end:
        yield day
        day += timedelta(days=1)
