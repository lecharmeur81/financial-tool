"""Derivatives calculated metrics and the Derivatives Health Score (pure functions).

Futures basis and options use real Deribit responses (tests/fixtures/derivatives); the other
series are small hand-designed timelines whose results are computed on paper in the comments.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from cfi.derivatives import metrics as m
from cfi.derivatives import score as sc
from cfi.derivatives.universe import dataset
from cfi.domain.enums import PitReliability, QualityStatus
from cfi.domain.observation import CanonicalQuote
from cfi.providers.base import FetchWindow, NormaliseContext, RawResponse
from cfi.providers.deribit import Deribit

FIXTURES = Path(__file__).parent.parent / "fixtures" / "derivatives"
AS_OF = datetime(2026, 9, 20, 12, tzinfo=UTC)
H = timedelta(hours=1)


def hourly(value: Decimal | int | str, hours: int = 8 * 24, end: datetime = AS_OF) -> list[m.Point]:
    """One point per hour up to ``end`` (inclusive)."""
    return [m.Point(end - i * H, Decimal(value)) for i in range(hours)][::-1]


def replace(points: list[m.Point], at: datetime, value: Decimal | int | str | None) -> None:
    for i, p in enumerate(points):
        if p.time == at:
            points[i] = m.Point(at, None if value is None else Decimal(value))


def q(x: Decimal | None, places: str = "0.000001") -> Decimal | None:
    return None if x is None else x.quantize(Decimal(places))


# --------------------------------------------------------------------------- open interest


def oi_series(okx_week_ago: bool = True) -> dict[str, list[m.Point]]:
    binance = hourly(90_000)
    replace(binance, AS_OF, 100_000)
    replace(binance, AS_OF - 24 * H, 95_000)
    okx = hourly(30_000)
    if not okx_week_ago:  # nothing within the 1-hour lookback tolerance
        replace(okx, AS_OF - 7 * 24 * H, None)
        replace(okx, AS_OF - 7 * 24 * H - H, None)
    return {"binance": binance, "okx": okx}


def test_open_interest_change_uses_only_venues_with_both_values() -> None:
    oi = m.open_interest(oi_series(), AS_OF)
    # 24 h: (100,000 + 30,000) ÷ (95,000 + 30,000) − 1 = 0.04; 7 d: 130,000 ÷ 120,000 − 1
    assert oi.total_now == 130_000
    assert oi.change_24h == Decimal("0.04")
    assert q(oi.change_7d) == Decimal("0.083333")
    assert oi.condition == "stable"
    one_venue = m.open_interest(oi_series(okx_week_ago=False), AS_OF)
    assert one_venue.venues_7d == ["binance"]  # never a mixed venue set
    assert q(one_venue.change_7d) == Decimal("0.111111")  # 100,000 ÷ 90,000 − 1


def test_open_interest_conditions() -> None:
    assert m.oi_condition(Decimal("0.05"), None)[0] == "expansion"
    assert m.oi_condition(Decimal("0.01"), Decimal("0.15"))[0] == "expansion"
    assert m.oi_condition(Decimal("-0.05"), Decimal("0.02"))[0] == "contraction"
    assert m.oi_condition(Decimal("0.06"), Decimal("-0.20"))[0] == "mixed"
    assert m.oi_condition(Decimal("0.049"), Decimal("-0.149"))[0] == "stable"
    assert m.oi_condition(None, None)[0] == "unknown"


def test_stale_open_interest_is_not_used_as_latest() -> None:
    old = {"okx": hourly(30_000, end=AS_OF - 4 * H)}
    oi = m.open_interest(old, AS_OF)
    assert oi.total_now is None
    assert oi.condition == "unknown"


# --------------------------------------------------------------------------- leverage


def test_leverage_ratio_change() -> None:
    series = oi_series()
    replace(series["binance"], AS_OF - 7 * 24 * H, 90_000)
    oi = m.open_interest(series, AS_OF)
    # price bars open one hour before each snapshot (their close is the price at the snapshot)
    price = [m.Point(AS_OF - H, Decimal(60_000)), m.Point(AS_OF - 7 * 24 * H - H, Decimal(50_000))]
    caps = [
        m.Point(datetime(2026, 9, 20, tzinfo=UTC), Decimal("1.2E12")),
        m.Point(datetime(2026, 9, 13, tzinfo=UTC), Decimal("1.0E12")),
    ]
    lev = m.leverage(oi, price, caps)
    # now 130,000 × 60,000 ÷ 1.2e12 = 0.0065; then 120,000 × 50,000 ÷ 1.0e12 = 0.006
    assert lev.ratio_now == Decimal("0.0065")
    assert lev.ratio_week_ago == Decimal("0.006")
    assert q(lev.change_7d) == Decimal("0.083333")
    assert lev.condition == "stable"
    component = sc.leverage_component(lev)
    assert component.stress == Decimal("0.4167")  # 0.0833 ÷ 0.20
    missing = m.leverage(oi, price[:1], caps)
    assert missing.status == "unavailable"
    assert "USD price 7 days earlier" in (missing.reason or "")


# --------------------------------------------------------------------------- funding


def settlements(rate: str, skip: datetime | None = None) -> list[m.Point]:
    """8-hourly settlements at 00:00, 08:00, 16:00 UTC from 2026-09-12 to AS_OF."""
    out, t = [], datetime(2026, 9, 12, tzinfo=UTC)
    while t <= AS_OF:
        if t != skip:
            out.append(m.Point(t, Decimal(rate)))
        t += 8 * H
    return out


def test_funding_is_annualised_from_the_sum_of_seven_days() -> None:
    oi = m.open_interest(oi_series(), AS_OF)
    f = m.funding({"binance": settlements("0.0001"), "okx": settlements("0.0003")}, oi, AS_OF)
    binance, okx = f.venues
    # 21 settlements in (09-13 12:00, 09-20 12:00]: Σ = 0.0021 → × 365 ÷ 7 = 0.1095
    assert binance.settlements == 21
    assert binance.annualised_7d == Decimal("0.1095")
    assert okx.annualised_7d == Decimal("0.3285")
    assert binance.interval_hours == 8
    assert binance.latest_annualised == Decimal("0.1095")  # 0.0001 × 3 a day × 365
    # OI-weighted: (0.1095 × 100,000 + 0.3285 × 30,000) ÷ 130,000
    assert q(f.annualised_7d) == Decimal("0.160038")
    assert f.condition == "normal"
    assert f.direction == "positive: long positions pay short positions"
    component = sc.funding_component(f)
    assert component.stress == Decimal("0.5335")  # 0.160038 ÷ 0.30
    assert component.value == Decimal("16.00")


def test_funding_with_a_missing_settlement_is_incomplete() -> None:
    oi = m.open_interest(oi_series(), AS_OF)
    gap = datetime(2026, 9, 17, 8, tzinfo=UTC)
    f = m.funding({"binance": settlements("0.0001"), "okx": settlements("0.0003", gap)}, oi, AS_OF)
    okx = f.venues[1]
    assert okx.status == "incomplete"
    assert okx.largest_gap_hours == 16
    assert okx.annualised_7d is None
    assert f.annualised_7d == Decimal("0.1095")  # Binance only, never a partial sum
    extreme = m.funding({"okx": settlements("-0.0006")}, oi, AS_OF)
    assert extreme.condition == "extreme_negative"  # −0.657 a year
    assert extreme.direction == "negative: short positions pay long positions"


# --------------------------------------------------------------------------- basis (real data)


def deribit_quotes(name: str, metric: str, received: datetime) -> list[m.Quote]:
    adapter = Deribit()
    window = FetchWindow(received - H, received, "BTC")
    spec = adapter.first_request(dataset(metric, "BTC").dataset_id, window)
    raw = RawResponse(
        "deribit",
        spec.path,
        dict(spec.params),
        received,
        200,
        "application/json",
        (FIXTURES / name).read_bytes(),
    )
    ctx = NormaliseContext(dataset(metric, "BTC"), received, 1)
    out = []
    for record in adapter.parse_page(spec, raw):
        c = adapter.normalise(record, ctx)
        assert isinstance(c, CanonicalQuote)
        out.append(
            m.Quote(
                c.event_time,
                c.instrument,
                c.instrument_kind,
                c.expiry,
                c.mark_price,
                c.index_price,
                c.open_interest_usd,
                c.strike,
                c.option_type,
                c.mark_iv,
                c.underlying_price,
                c.open_interest_native,
                c.volume_native,
            )
        )
    return out


def test_basis_from_the_real_deribit_curve() -> None:
    received = datetime(2026, 9, 26, 7, 8, 18, tzinfo=UTC)
    quotes = deribit_quotes("deribit_future_BTC.json", "futures_curve", received)
    b = m.basis(quotes, received, timedelta(hours=3))
    assert b.status == "ok"
    assert len(b.curve) == 13
    assert b.headline is not None
    # closest to 90 days (≥ 14): BTC-25DEC26, 90.0359 days after the 07:08:17 snapshot
    assert b.headline.instrument == "BTC-25DEC26"
    assert q(b.headline.days, "0.0001") == Decimal("90.0359")
    # (85,024.53 ÷ 83,996.18 − 1) × 365 ÷ 90.0359 = 0.049632
    assert q(b.headline.premium) == Decimal("0.012243")
    assert q(b.headline.annualised) == Decimal("0.049632")
    assert q(b.perpetual_premium, "0.0000001") == Decimal("0.0000320")
    assert (b.condition, b.shape) == ("normal", "contango")
    assert sc.basis_component(b).stress == 0  # inside 0 … 10 % a year
    stale = m.basis(quotes, received + timedelta(hours=4), timedelta(hours=3))
    assert stale.status == "unavailable"


def test_basis_component_stress_outside_the_band() -> None:
    point = m.CurvePoint(
        "X", None, Decimal(90), Decimal(1), Decimal(1), Decimal(0), Decimal("0.19"), None
    )
    b = m.Basis("ok", None, AS_OF, [point], point, None, "normal", "contango")
    assert sc.basis_component(b).stress == Decimal("0.6000")  # (19 % − 10 %) ÷ 15 %
    point.annualised = Decimal("-0.03")
    assert sc.basis_component(b).stress == Decimal("0.2000")  # 3 % below 0 ÷ 15 %
    assert sc.basis_component(None).status == "not_applicable"


# --------------------------------------------------------------------------- options (real data)


def test_options_from_the_real_deribit_excerpt() -> None:
    received = datetime(2026, 9, 25, 14, 29, tzinfo=UTC)
    quotes = deribit_quotes("deribit_option_BTC_30OCT26_excerpt.json", "option_chain", received)
    o = m.options(quotes, received, timedelta(hours=9))
    assert o.status == "ok"
    assert o.instruments == 23
    # 15 calls, 8 puts of the 30OCT26 excerpt
    assert (o.call_oi, o.put_oi) == (Decimal("47286.1"), Decimal("2367.3"))
    assert q(o.put_call_oi, "0.0001") == Decimal("0.0501")
    assert (o.call_volume, o.put_volume) == (Decimal("4913.6"), Decimal("394.4"))
    assert q(o.put_call_volume, "0.0001") == Decimal("0.0803")
    assert o.notional_oi_usd == Decimal("4150289369.68")  # 49,653.4 × 83,585.2
    assert o.expiry == datetime(2026, 10, 30, 8, tzinfo=UTC)
    assert q(o.expiry_days, "0.0001") == Decimal("34.7301")
    assert o.forward == Decimal("83995.83")  # median forward of the expiry
    assert (o.atm_strike, o.atm_iv) == (Decimal(84000), Decimal("0.3469"))
    # 0.9 × F = 75,596.25 → put 76,000 (36.61 %); 1.1 × F = 92,395.41 → call 90,000 (34.86 %)
    assert o.skew_put == (Decimal(76000), Decimal("0.3661"))
    assert o.skew_call == (Decimal(90000), Decimal("0.3486"))
    assert o.skew == Decimal("0.0175")


def test_skew_needs_strikes_near_the_targets() -> None:
    expiry = AS_OF + timedelta(days=30)

    def opt(strike: int, kind: str, iv: str) -> m.Quote:
        return m.Quote(
            AS_OF, f"X-{strike}-{kind}", "option", expiry, Decimal("0.01"), Decimal(100),
            strike=Decimal(strike), option_type=kind, mark_iv=Decimal(iv),
            underlying=Decimal(100), open_interest=Decimal(1), volume=Decimal(1),
        )  # fmt: skip

    far = [opt(80, "put", "0.6"), opt(100, "call", "0.5"), opt(100, "put", "0.5")]
    o = m.options(far, AS_OF, timedelta(hours=9))
    assert o.skew is None
    assert "0.9 × forward" in (o.skew_reason or "")
    assert o.atm_iv == Decimal("0.5")
    near_expiry = [
        m.Quote(AS_OF, "Y", "option", AS_OF + timedelta(days=3), Decimal(1), Decimal(1),
                strike=Decimal(100), option_type="call", mark_iv=Decimal("0.5"))
    ]  # fmt: skip
    assert m.options(near_expiry, AS_OF, timedelta(hours=9)).skew_reason == (
        "no expiry at least 7 days away"
    )


# --------------------------------------------------------------------------- liquidations


def liquidation_history() -> tuple[list[m.Point], list[m.Point], list[m.Point]]:
    """168 complete hours up to 11:00 (AS_OF − 2 min floors to 11:00): 0.6 long + 0.4 short
    each, except 05:00 on 2026-09-20: 18 long + 2 short."""
    last = datetime(2026, 9, 20, 10, tzinfo=UTC)
    long = [m.Point(last - i * H, Decimal("0.6")) for i in range(168)][::-1]
    short = [m.Point(last - i * H, Decimal("0.4")) for i in range(168)][::-1]
    spike = datetime(2026, 9, 20, 5, tzinfo=UTC)
    replace(long, spike, 18)
    replace(short, spike, 2)
    return long, short, hourly(30_000)


def test_liquidations_last_24_hours_and_events() -> None:
    long, short, oi = liquidation_history()
    liq = m.liquidations(long, short, oi, AS_OF)
    assert (liq.window_start, liq.window_end) == (
        datetime(2026, 9, 19, 11, tzinfo=UTC),
        datetime(2026, 9, 20, 11, tzinfo=UTC),
    )
    # 23 ordinary hours + the spike: long 23 × 0.6 + 18 = 31.8, short 23 × 0.4 + 2 = 11.2
    assert (liq.long_24h, liq.short_24h, liq.total_24h) == (
        Decimal("31.8"),
        Decimal("11.2"),
        Decimal("43.0"),
    )
    assert q(liq.share_of_oi) == Decimal("0.001433")  # 43 ÷ 30,000
    assert q(liq.long_share, "0.0001") == Decimal("0.7395")
    assert liq.status == "ok"
    # the spike hour: 20 ≥ 5 × median 1 and 20 ÷ 30,000 = 0.067 % ≥ 0.05 %
    assert [(e.hour.hour, e.total, e.median_before) for e in liq.events] == [
        (5, Decimal(20), Decimal(1))
    ]
    component = sc.liquidation_component(liq)
    assert component.stress == Decimal("0.1433")  # 0.1433 % ÷ 1 %
    assert "74 % of liquidated size was long" in (component.context or "")
    # RED_TEAM_REPORT.md finding #9: single-venue liquidation data must be flagged, not treated
    # as equally reliable as the multi-venue components (e.g. funding) beside it.
    assert "single-venue" in (component.context or "").lower()


def test_liquidations_with_missing_hours_or_short_history() -> None:
    long, short, oi = liquidation_history()
    del long[-3]  # one hour of the last 24 missing
    liq = m.liquidations(long, short, oi, AS_OF)
    assert liq.status == "incomplete"
    assert liq.share_of_oi is None
    assert sc.liquidation_component(liq).status == "unavailable"
    recent = m.liquidations(long[-20:], short[-20:], oi, AS_OF)
    assert recent.events == []
    assert "more than 24 stored hours" in (recent.events_note or "")
    nothing = m.liquidations([], [], oi, AS_OF)
    assert nothing.status == "unavailable"
    assert nothing.events_note == "events need more than 24 stored hours (0 so far)"


# --------------------------------------------------------------------------- context


def test_price_and_open_interest_context_has_no_direction_call() -> None:
    text = m.price_oi_context(Decimal("0.03"), Decimal("0.06"))
    assert text == (
        "Price rising with open interest rising: new positions are being opened as price moves."
    )
    assert "closed" in (m.price_oi_context(Decimal("-0.03"), Decimal("-0.02")) or "")
    assert "roughly unchanged" in (m.price_oi_context(Decimal("0.05"), Decimal("0.005")) or "")
    for words in ("bull", "bear", "buy", "sell"):
        assert words not in (m.price_oi_context(Decimal("0.03"), Decimal("0.06")) or "").lower()


# --------------------------------------------------------------------------- score


def component(cid: str, stress: str | None, status: sc.Status = "ok") -> sc.ComponentResult:
    return sc.ComponentResult(
        sc.DEFS[cid], status, stress=None if stress is None else Decimal(stress)
    )


def test_health_score_combines_available_components() -> None:
    parts = [
        component("funding", "0.5"),
        component("basis", "0"),
        component("leverage", "0.4"),
        component("liquidations", "0.2"),
        component("volatility", "0.1"),
    ]
    s = sc.compute("BTC", AS_OF, parts)
    # stress = 0.25 × 0.5 + 0.15 × 0 + 0.20 × 0.4 + 0.20 × 0.2 + 0.20 × 0.1 = 0.265
    assert (s.stress, s.health, s.band) == (Decimal("26.5"), Decimal("73.5"), "moderate stress")
    assert [c.contribution for c in parts] == [
        Decimal("12.50"),
        Decimal("0.00"),
        Decimal("8.00"),
        Decimal("4.00"),
        Decimal("2.00"),
    ]


def test_health_score_without_options_data_reweights() -> None:
    parts = [
        component("funding", "0.5"),
        component("basis", None, "not_applicable"),
        component("leverage", "0.4"),
        component("liquidations", "0.2"),
        component("volatility", None, "not_applicable"),
    ]
    s = sc.compute("SOL", AS_OF, parts)
    # (0.125 + 0.08 + 0.04) ÷ 0.65 = 0.376923
    assert (s.stress, s.health, s.band) == (Decimal("37.7"), Decimal("62.3"), "moderate stress")
    assert s.available_weight == Decimal("0.65")


def test_health_score_needs_half_of_the_weight() -> None:
    parts = [
        component("funding", "0.9"),
        component("basis", None, "unavailable"),
        component("leverage", None, "unavailable"),
        component("liquidations", "0.1"),
        component("volatility", None, "unavailable"),
    ]
    s = sc.compute("ETH", AS_OF, parts)
    assert s.status == "insufficient_data"
    assert s.health is None
    assert "Insufficient data" in (s.reason or "")


@pytest.mark.parametrize(
    ("health", "band"),
    [("75", "low stress"), ("74.9", "moderate stress"), ("50", "moderate stress"),
     ("25", "elevated stress"), ("24.9", "high stress")],
)  # fmt: skip
def test_bands(health: str, band: str) -> None:
    assert sc.band_for(Decimal(health)) == band


def test_volatility_component_scales_per_asset() -> None:
    btc = sc.volatility_component("BTC", m.Point(AS_OF, Decimal("0.3462")), True)
    assert btc.stress == Decimal("0.0924")  # (34.62 − 30) ÷ (80 − 30)
    eth = sc.volatility_component("ETH", m.Point(AS_OF, Decimal("1.2")), True)
    assert eth.stress == 1
    assert sc.volatility_component("SOL", None, False).status == "not_applicable"


def test_expired_instruments_are_left_out_and_flagged() -> None:
    expired = m.Quote(
        AS_OF, "BTC-1SEP26", "future", AS_OF - timedelta(days=2), Decimal(101), Decimal(100)
    )
    live = m.Quote(
        AS_OF, "BTC-25DEC26", "future", AS_OF + timedelta(days=90), Decimal(102), Decimal(100)
    )
    b = m.basis([expired, live], AS_OF, timedelta(hours=3))
    assert [c.instrument for c in b.curve] == ["BTC-25DEC26"]
    quote = CanonicalQuote(
        dataset_id="deriv.futures_curve.btc",
        metric="futures_curve",
        asset="BTC",
        subject_ref="DERIBIT:BTC-1SEP26",
        period="event",
        unit="usd",
        event_time=AS_OF,
        available_at=AS_OF,
        available_at_estimated=False,
        ingested_at=AS_OF,
        source_provider="deribit",
        original_source="deribit",
        quality_status=QualityStatus.OK,
        pit_reliability=PitReliability.NATIVE,
        instrument="BTC-1SEP26",
        instrument_kind="future",
        expiry=AS_OF - timedelta(days=2),
        mark_price=Decimal(101),
    )
    assert quote.consistency_problems() == ["instrument listed after its expiry"]
