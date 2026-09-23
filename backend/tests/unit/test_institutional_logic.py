"""Aggregation and Institutional Flow Score on the synthetic historical fixtures (pure logic).

Expected values are derived by hand in tests/fixtures/institutional/README.md.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.institutional.aggregation import DailyPoint, aggregate, etf_due_date, trading_window
from cfi.institutional.score import (
    COMPONENTS,
    Purchase,
    band_for,
    compute_score,
)
from tests.institutional_fakes import fixture

AS_OF = datetime(2026, 9, 9, 12, tzinfo=UTC)
M = Decimal(1_000_000)


def points(asset: str = "BTC", drop: tuple[str, ...] = ()) -> list[DailyPoint]:
    out = []
    for row in fixture(f"sosovalue_etf_summary_{asset}.json")["data"]:
        if row["total_net_inflow"] is None or row["date"] in drop:
            continue
        day = date.fromisoformat(row["date"])
        out.append(
            DailyPoint(
                day=day,
                flow_usd=Decimal(row["total_net_inflow"]),
                holdings_usd=Decimal(row["total_net_assets"]),
                value_traded_usd=Decimal(row["total_value_traded"]),
                quality_status="ok",
                revision=0,
                pit_reliability="native",
                available_at_estimated=True,
                available_at=datetime(day.year, day.month, day.day, tzinfo=UTC),
                ingested_at=AS_OF,
            )
        )
    return sorted(out, key=lambda p: p.day)


def treasury() -> tuple[list[Purchase], dict[str, Decimal]]:
    purchases, holdings = [], {}
    for ticker in ("TSTA", "TSTB", "TSTC"):
        rows = fixture(f"sosovalue_purchase_history_{ticker}.json")["data"]
        for row in rows:
            purchases.append(
                Purchase(
                    day=date.fromisoformat(row["date"]),
                    company=ticker,
                    flow_native=Decimal(row["btc_acq"]),
                    quality_status="ok",
                    pit_reliability="native",
                    available_at_estimated=True,
                )
            )
        latest = max(rows, key=lambda r: r["date"])
        holdings[ticker] = Decimal(latest["btc_holding"])
    return purchases, holdings


# --------------------------------------------------------------------------- due dates


def test_due_date_follows_the_next_trading_day_rule() -> None:
    # Wed 2026-09-09 12:00 UTC: Tue 09-08 is due only at 22:00 UTC on 09-09 → latest due Fri 09-04
    assert etf_due_date(AS_OF) == date(2026, 9, 4)
    assert etf_due_date(datetime(2026, 9, 9, 22, 0, tzinfo=UTC)) == date(2026, 9, 8)
    # Labor Day: Friday's data is due Tuesday 18:00 New York, not Monday
    assert etf_due_date(datetime(2026, 9, 8, 21, 59, tzinfo=UTC)) == date(2026, 9, 3)


def test_trading_window_skips_weekends_and_holidays() -> None:
    assert trading_window(date(2026, 9, 8), 3) == [
        date(2026, 9, 3),
        date(2026, 9, 4),
        date(2026, 9, 8),
    ]


# --------------------------------------------------------------------------- aggregation


def test_weekly_totals_match_the_hand_computed_fixture() -> None:
    buckets = aggregate(
        points(),
        interval="1w",
        start=date(2026, 8, 3),
        end=date(2026, 9, 10),
        due_until=date(2026, 9, 4),
        coverage_start=date(2026, 8, 3),
    )
    totals = [(b.start, b.net_flow_usd, b.status) for b in buckets]
    assert totals == [
        (date(2026, 8, 3), -400 * M, "complete"),
        (date(2026, 8, 10), 100 * M, "complete"),
        (date(2026, 8, 17), 100 * M, "complete"),
        (date(2026, 8, 24), 300 * M, "complete"),
        (date(2026, 8, 31), 1000 * M, "complete"),
        (date(2026, 9, 7), None, "not_due"),  # Labor Day week: Tue/Wed not reported yet
    ]
    assert buckets[-1].trading_days == 2
    assert buckets[4].holdings_usd_end == 100_000 * M
    assert buckets[4].holdings_date == date(2026, 9, 4)
    assert (buckets[3].inflow_days, buckets[3].outflow_days) == (3, 1)  # one zero-flow day


def test_monthly_buckets_distinguish_missing_not_loaded_and_not_due() -> None:
    buckets = aggregate(
        points(drop=("2026-09-02",)),
        interval="1mo",
        start=date(2026, 7, 27),
        end=date(2026, 9, 10),
        due_until=date(2026, 9, 4),
        coverage_start=date(2026, 8, 3),
    )
    july, august, september = buckets
    assert july.status == "not_loaded"
    assert july.not_loaded == 5  # 27-31 July: before stored history, not "missing"
    assert august.status == "complete"
    assert august.net_flow_usd == (-400 + 100 + 100 + 300 + 200) * M
    assert september.status == "partial"
    assert september.missing_days == [date(2026, 9, 2)]
    assert september.not_due == 2  # 8 and 9 September
    assert september.net_flow_usd == (300 + 400 + 200) * M  # present days only, nothing filled


# --------------------------------------------------------------------------- score


def test_btc_score_matches_the_hand_computed_fixture() -> None:
    purchases, holdings = treasury()
    result = compute_score(
        asset="BTC",
        as_of=AS_OF,
        etf_points=points(),
        due_until=etf_due_date(AS_OF),
        purchases=purchases,
        holdings=holdings,
    )
    by_id = {c.definition.component_id: c for c in result.components}
    assert by_id["etf_flow_5d"].value == Decimal("1.0000")
    assert by_id["etf_flow_5d"].sub_score == Decimal("1.0000")
    assert (by_id["etf_flow_5d"].window_start, by_id["etf_flow_5d"].window_end) == (
        date(2026, 8, 31),
        date(2026, 9, 4),
    )
    assert by_id["etf_flow_20d"].value == Decimal("1.5000")
    assert by_id["etf_flow_20d"].sub_score == Decimal("0.5000")
    assert by_id["etf_flow_breadth_10d"].value == Decimal("0.5000")
    assert by_id["treasury_net_acq_30d"].value == Decimal("1.2000")
    assert by_id["treasury_net_acq_30d"].sub_score == Decimal("0.6000")
    assert by_id["treasury_net_acq_30d"].inputs["purchase_events"] == 3
    assert result.status == "ok"
    assert result.score == Decimal("69.5")
    assert result.band == "strong net inflow"
    assert sum(c.contribution or 0 for c in result.components) == Decimal("69.50")
    assert "1,000.0M" in by_id["etf_flow_5d"].calculation  # numbers shown in the calculation


def test_missing_component_is_excluded_and_weights_renormalised() -> None:
    result = compute_score(
        asset="ETH",
        as_of=AS_OF,
        etf_points=points("ETH"),
        due_until=etf_due_date(AS_OF),
        purchases=[],
        holdings={},
    )
    treasury_c = next(c for c in result.components if c.definition.component_id.startswith("tr"))
    assert treasury_c.status == "unavailable"
    assert treasury_c.reason is not None
    assert "ETH" in treasury_c.reason
    assert result.available_weight == Decimal("0.80")
    assert result.score == Decimal("71.9")  # 100 * 0.575 / 0.80 = 71.875
    ok = [c for c in result.components if c.status == "ok"]
    assert sum(c.effective_weight or 0 for c in ok) == Decimal("1.0000")


def test_missing_day_excludes_the_short_window_and_is_reported() -> None:
    purchases, holdings = treasury()
    result = compute_score(
        asset="BTC",
        as_of=AS_OF,
        etf_points=points(drop=("2026-09-02",)),
        due_until=etf_due_date(AS_OF),
        purchases=purchases,
        holdings=holdings,
    )
    by_id = {c.definition.component_id: c for c in result.components}
    five = by_id["etf_flow_5d"]
    assert five.status == "unavailable"
    assert five.reason is not None
    assert "4 of 5" in five.reason
    assert "2026-09-02" in five.reason
    assert by_id["etf_flow_20d"].sub_score == Decimal("0.5333")
    assert by_id["etf_flow_20d"].missing_days == [date(2026, 9, 2)]
    assert by_id["etf_flow_breadth_10d"].value == Decimal("0.6667")
    expected = (
        100
        * (
            Decimal("0.30") * Decimal("0.5333")
            + Decimal("0.15") * Decimal("0.6667")
            + Decimal("0.20") * Decimal("0.6")
        )
        / Decimal("0.65")
    ).quantize(Decimal("0.1"))
    assert result.score == expected == Decimal("58.5")


def test_too_little_data_gives_insufficient_data_not_a_number() -> None:
    result = compute_score(
        asset="BTC",
        as_of=AS_OF,
        etf_points=points()[-4:],  # only four days stored
        due_until=etf_due_date(AS_OF),
        purchases=[],
        holdings={},
    )
    assert result.status == "insufficient_data"
    assert result.score is None
    assert result.band is None
    assert result.reason is not None
    assert "Insufficient data" in result.reason


def test_sub_scores_are_capped() -> None:
    boosted = [
        DailyPoint(
            day=p.day,
            flow_usd=(p.flow_usd or Decimal(0)) * 10,
            holdings_usd=p.holdings_usd,
            value_traded_usd=p.value_traded_usd,
            quality_status=p.quality_status,
            revision=p.revision,
            pit_reliability=p.pit_reliability,
            available_at_estimated=p.available_at_estimated,
            available_at=p.available_at,
            ingested_at=p.ingested_at,
        )
        for p in points()
    ]
    result = compute_score(
        asset="ETH",
        as_of=AS_OF,
        etf_points=boosted,
        due_until=etf_due_date(AS_OF),
        purchases=[],
        holdings={},
    )
    five = next(c for c in result.components if c.definition.component_id == "etf_flow_5d")
    assert five.value == Decimal("10.0000")
    assert five.sub_score == Decimal("1.0000")


@pytest.mark.parametrize(
    ("score", "band"),
    [
        ("100", "strong net inflow"),
        ("50", "strong net inflow"),
        ("49.9", "net inflow"),
        ("15", "net inflow"),
        ("0", "balanced"),
        ("-15", "balanced"),
        ("-15.1", "net outflow"),
        ("-50", "net outflow"),
        ("-50.1", "strong net outflow"),
    ],
)
def test_bands_include_their_lower_bound(score: str, band: str) -> None:
    assert band_for(Decimal(score)) == band


def test_published_weights_sum_to_one() -> None:
    assert sum(c.weight for c in COMPONENTS) == Decimal(1)


def test_score_ignores_data_dated_after_as_of() -> None:
    """Rows for days after the as_of date never enter a window (belt-and-braces: the query also
    filters on available_at)."""
    pts = points()
    later = DailyPoint(
        day=date(2026, 9, 10),
        flow_usd=Decimal(10**15),
        holdings_usd=100_000 * M,
        value_traded_usd=None,
        quality_status="ok",
        revision=0,
        pit_reliability="native",
        available_at_estimated=True,
        available_at=AS_OF + timedelta(days=2),
        ingested_at=AS_OF + timedelta(days=2),
    )
    base = compute_score(
        asset="ETH",
        as_of=AS_OF,
        etf_points=pts,
        due_until=etf_due_date(AS_OF),
        purchases=[],
        holdings={},
    )
    poisoned = compute_score(
        asset="ETH",
        as_of=AS_OF,
        etf_points=[*pts, later],
        due_until=etf_due_date(AS_OF),
        purchases=[],
        holdings={},
    )
    assert poisoned.score == base.score
