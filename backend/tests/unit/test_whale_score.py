"""Whale Flow Score, accumulation/distribution components and contradiction indicators (pure).

Expected values are the hand computations of tests/fixtures/whales/README.md.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from cfi.institutional.score import ComponentResult, ScoreResult
from cfi.whales import score as ws
from tests.whale_fakes import COINMETRICS, LAST_DAY, btc_address, btc_daily, days

NOW = datetime(2026, 9, 10, 12, tzinfo=UTC)
END = LAST_DAY
IDS = {"FlowInExNtv": "inflow", "FlowOutExNtv": "outflow", "SplyExNtv": "supply"}


def series(asset: str, metric_id: str, drop: tuple[date, ...] = ()) -> dict[date, ws.DayValue]:
    return {d: ws.DayValue(d, COINMETRICS[asset](d)[metric_id]) for d in days() if d not in drop}


def revived(drop: tuple[date, ...] = ()) -> dict[date, ws.DayValue]:
    return {
        d: ws.DayValue(d, btc_daily("revived_supply_1y", d) / 100_000_000)
        for d in days()
        if d not in drop
    }


UNKNOWN = [btc_address(i) for i in range(10)]
EXCHANGE = btc_address(50)


def snap(when: datetime, unknown_balance: Decimal, exchange: Decimal) -> ws.Snapshot:
    balances = {a: unknown_balance for a in UNKNOWN} | {EXCHANGE: exchange}
    classes = {a: "unknown_large_holder" for a in UNKNOWN} | {EXCHANGE: "exchange"}
    return ws.Snapshot(when, balances, classes)


SNAPS = [
    snap(datetime(2026, 9, 3, 6, tzinfo=UTC), Decimal(10_000), Decimal(250_000)),
    snap(datetime(2026, 9, 10, 6, tzinfo=UTC), Decimal(10_100), Decimal(245_000)),
]


def inputs(asset: str = "BTC", **kw: object) -> ws.ScoreInputs:
    base: dict[str, object] = {
        "asset": asset,
        "unit": asset.lower(),
        "as_of": NOW,
        "end": END,
        "inflow": series(asset.lower(), "FlowInExNtv"),
        "outflow": series(asset.lower(), "FlowOutExNtv"),
        "exchange_supply": series(asset.lower(), "SplyExNtv"),
        "revived": revived() if asset == "BTC" else {},
        "snapshots": SNAPS if asset == "BTC" else [],
    }
    return ws.ScoreInputs(**(base | kw))  # type: ignore[arg-type]


def by_id(result: ScoreResult) -> dict[str, ComponentResult]:
    return {c.definition.component_id: c for c in result.components}


def test_btc_score_matches_the_hand_computation() -> None:
    result, change = ws.compute_score(inputs())
    c = by_id(result)
    assert (c["exchange_netflow_7d"].value, c["exchange_netflow_7d"].sub_score) == (
        Decimal("-0.2506"),
        Decimal("0.2506"),
    )
    assert c["exchange_netflow_7d"].inputs["net_flow_to_exchanges_btc"] == "-7000"
    assert (c["exchange_supply_30d"].value, c["exchange_supply_30d"].sub_score) == (
        Decimal("-0.2500"),
        Decimal("0.0833"),
    )
    assert (c["large_holders_7d"].value, c["large_holders_7d"].sub_score) == (
        Decimal("1.0000"),
        Decimal("1.0000"),
    )
    assert (c["revived_1y_7d"].value, c["revived_1y_7d"].sub_score) == (
        Decimal("1.5000"),
        Decimal("-0.5000"),
    )
    assert result.status == "ok"
    assert result.score == Decimal("22.5")
    assert result.band == "accumulation"
    assert result.available_weight == Decimal("1.00")
    assert change is not None
    assert (change.matched, change.left, change.entered) == (10, 0, 0)
    assert sum(x.contribution or 0 for x in result.components) == pytest.approx(
        Decimal("22.52"), abs=Decimal("0.01")
    )


def test_eth_score_renormalises_over_the_available_weight() -> None:
    result, _ = ws.compute_score(inputs("ETH"))
    c = by_id(result)
    assert c["exchange_netflow_7d"].value == Decimal("0.4645")
    assert c["exchange_netflow_7d"].sub_score == Decimal("-0.4645")
    assert c["exchange_supply_30d"].sub_score == Decimal("-0.1556")
    assert c["large_holders_7d"].status == "unavailable"
    assert c["revived_1y_7d"].reason == "coin-age data is tracked for Bitcoin only, not ETH"
    assert result.available_weight == Decimal("0.50")
    assert result.score == Decimal("-37.2")
    assert result.band == "distribution"
    assert c["exchange_netflow_7d"].effective_weight == Decimal("0.7000")


def test_a_missing_day_excludes_the_seven_day_component_never_fills_it() -> None:
    gap = date(2026, 9, 6)
    result, _ = ws.compute_score(inputs(outflow=series("btc", "FlowOutExNtv", drop=(gap,))))
    net = by_id(result)["exchange_netflow_7d"]
    assert net.status == "unavailable"
    assert net.missing_days == [gap]
    assert net.reason is not None
    assert "only 6 of 7 days" in net.reason
    # the remaining components (0.65) still produce a score
    assert result.status == "ok"
    assert result.available_weight == Decimal("0.65")


def test_exchange_supply_needs_both_endpoints() -> None:
    start = END - timedelta(days=30)
    result, _ = ws.compute_score(inputs(exchange_supply=series("btc", "SplyExNtv", drop=(start,))))
    supply = by_id(result)["exchange_supply_30d"]
    assert supply.status == "unavailable"
    assert supply.reason == f"exchange supply missing on {start.isoformat()}"


def test_revived_baseline_coverage_and_zero_baseline() -> None:
    baseline_gaps = tuple(END - timedelta(days=10 + i) for i in range(10))  # 80 of 90 days
    result, _ = ws.compute_score(inputs(revived=revived(drop=baseline_gaps)))
    rev = by_id(result)["revived_1y_7d"]
    assert rev.status == "unavailable"
    assert rev.reason is not None
    assert "90-day baseline: only 80 of 90 days" in rev.reason
    zero = {d: ws.DayValue(d, Decimal(0)) for d in days()}
    rev0 = ws.revived_component(zero, END, "BTC")
    assert rev0.reason == "no coins ≥ 1 year old moved in the baseline period"


def test_sub_scores_are_capped() -> None:
    flood = {d: ws.DayValue(d, Decimal(10**6)) for d in days()}
    result, _ = ws.compute_score(inputs(inflow=flood))
    assert by_id(result)["exchange_netflow_7d"].sub_score == Decimal(-1)


def test_holder_component_needs_a_snapshot_a_week_earlier() -> None:
    later = [SNAPS[1]]
    comp, change = ws.large_holder_component(later, NOW, "btc")
    assert change is None
    assert comp.reason is not None
    assert "no snapshot 7 days" in comp.reason
    comp, _ = ws.large_holder_component([], NOW, "btc")
    assert comp.reason == "no top-100 balance snapshot stored yet"
    # ± 1 day tolerance
    shifted = [
        ws.Snapshot(SNAPS[0].time + timedelta(hours=20), SNAPS[0].balances, SNAPS[0].classes),
        SNAPS[1],
    ]
    assert ws.large_holder_component(shifted, NOW, "btc")[0].status == "ok"


def test_holders_leaving_the_list_are_reported_and_can_disable_the_component() -> None:
    now = SNAPS[1]
    remaining = {a: b for a, b in now.balances.items() if a not in UNKNOWN[:3]}
    shrunk = ws.Snapshot(now.time, remaining, {a: now.classes[a] for a in remaining})
    comp, change = ws.large_holder_component([SNAPS[0], shrunk], NOW, "btc")
    assert change is not None
    assert (change.considered, change.matched, change.left) == (10, 7, 3)
    assert comp.status == "unavailable"  # 70 % < 80 %
    assert comp.reason is not None
    assert "only 7 of 10" in comp.reason


def test_class_membership_comes_from_the_earlier_snapshot() -> None:
    newcomer = btc_address(77)
    now = ws.Snapshot(
        SNAPS[1].time,
        {**SNAPS[1].balances, newcomer: Decimal(90_000)},
        {**SNAPS[1].classes, newcomer: "unknown_large_holder"},
    )
    change = ws.holder_change(now, SNAPS[0], "unknown_large_holder")
    assert (change.entered, change.matched) == (1, 10)
    assert change.balance_now == Decimal(101_000)  # the newcomer's 90,000 is not "growth"


def test_snapshots_after_as_of_are_invisible() -> None:
    now, then = ws.pick_snapshots(SNAPS, datetime(2026, 9, 6, tzinfo=UTC))
    assert now is SNAPS[0]
    assert then is None


def test_insufficient_data_below_half_the_weight() -> None:
    empty: dict[date, ws.DayValue] = {}
    result, _ = ws.compute_score(
        inputs(inflow=empty, outflow=empty, exchange_supply=empty, revived=empty)
    )
    assert result.status == "insufficient_data"
    assert result.score is None
    assert result.reason is not None
    assert result.reason.startswith("Insufficient data")


@pytest.mark.parametrize(
    ("score", "band"),
    [
        (Decimal(50), "strong accumulation"),
        (Decimal("49.9"), "accumulation"),
        (Decimal(15), "accumulation"),
        (Decimal("14.9"), "neutral"),
        (Decimal(-15), "neutral"),
        (Decimal("-15.1"), "distribution"),
        (Decimal(-50), "distribution"),
        (Decimal("-50.1"), "strong distribution"),
    ],
)
def test_bands(score: Decimal, band: str) -> None:
    assert ws.band_for(score) == band


def test_due_day_and_window_end() -> None:
    t = datetime(2026, 9, 24, 12, tzinfo=UTC)
    assert ws.due_day(t, timedelta(hours=12)) == date(2026, 9, 23)
    assert ws.due_day(datetime(2026, 9, 24, 11, tzinfo=UTC), timedelta(hours=12)) == date(
        2026, 9, 22
    )
    early = {date(2026, 9, 23): ws.DayValue(date(2026, 9, 23), Decimal(1))}
    # data already received counts even before the conservative due time
    assert ws.window_end([early], date(2026, 9, 22), datetime(2026, 9, 24, 3, tzinfo=UTC)) == date(
        2026, 9, 23
    )
    # but never a day that has not ended at as_of
    today = {date(2026, 9, 24): ws.DayValue(date(2026, 9, 24), Decimal(1))}
    assert ws.window_end([today], date(2026, 9, 22), t) == date(2026, 9, 22)


def test_miner_spending_ratio() -> None:
    spent = {d: ws.DayValue(d, Decimal(450)) for d in days()}
    issued = {d: ws.DayValue(d, Decimal(450)) for d in days()}
    ratio = ws.miner_spending_ratio(spent, issued, END)
    assert (ratio.status, ratio.value, ratio.numerator) == ("ok", Decimal("1.0000"), Decimal(3150))
    del issued[END]
    assert ws.miner_spending_ratio(spent, issued, END).status == "unavailable"


# ------------------------------------------------------------------ contradictions


def checks(**kw: object) -> dict[str, ws.Contradiction]:
    result, _ = ws.compute_score(inputs())
    args: dict[str, object] = {
        "institutional_score": None,
        "institutional_status": "insufficient_data",
        "richlist_exchange_change_pct": Decimal(-2),
        "coinmetrics_exchange_change_pct": Decimal("-0.25"),
    }
    return {c.indicator_id: c for c in ws.contradictions(result, **(args | kw))}  # type: ignore[arg-type]


def test_contradiction_indicators_for_the_fixture() -> None:
    c = checks()
    old = c["exchange_flows_vs_old_coins"]
    assert old.status == "contradiction"
    assert [r.direction for r in old.readings] == ["accumulation", "distribution"]
    assert c["exchange_flows_vs_large_holders"].status == "consistent"
    etf = c["whales_vs_etf"]
    assert etf.status == "insufficient_data"
    assert etf.explanation == "Insufficient data: Institutional Flow Score."
    assert c["exchange_balances_two_sources"].status == "no_clear_direction"


def test_whales_vs_etf_contradiction_and_agreement() -> None:
    assert (
        checks(institutional_score=Decimal(-40), institutional_status="ok")["whales_vs_etf"].status
        == "contradiction"
    )
    assert (
        checks(institutional_score=Decimal(30), institutional_status="ok")["whales_vs_etf"].status
        == "consistent"
    )
    # a score reported with status "insufficient_data" is never compared
    assert (
        checks(institutional_score=Decimal(30), institutional_status="insufficient_data")[
            "whales_vs_etf"
        ].status
        == "insufficient_data"
    )


def test_exchange_balance_sources_disagreeing() -> None:
    c = checks(coinmetrics_exchange_change_pct=Decimal("1.2"))["exchange_balances_two_sources"]
    assert c.status == "contradiction"
    assert [r.direction for r in c.readings] == ["accumulation", "distribution"]


def test_direction_thresholds() -> None:
    assert ws.direction_of(None, Decimal(1)) == "unknown"
    assert ws.direction_of(Decimal("0.25"), ws.DIRECTION_THRESHOLD) == "accumulation"
    assert ws.direction_of(Decimal("0.2499"), ws.DIRECTION_THRESHOLD) == "neutral"
    assert ws.direction_of(Decimal("-0.25"), ws.DIRECTION_THRESHOLD) == "distribution"
