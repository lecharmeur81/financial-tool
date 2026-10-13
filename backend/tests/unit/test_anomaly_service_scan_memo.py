"""``AnomalyService.scan``: the full output is pinned to a golden captured from the unmodified
code, and each metric's reading is computed once per scan (not once per metric plus once per
counterpart reference).

The adapters are a deterministic in-memory fake (synthetic daily series with trends, wobble, gaps
and a final spike), so the real service, the real metric functions and the real band
classification run end to end without any database. These tests prove behavioural identity of the
memoisation; they say nothing about production data volumes or runtime.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cfi.anomaly import metrics as anomaly_metrics
from cfi.anomaly.service import AnomalyService
from cfi.anomaly.universe import METRICS_BY_ID
from cfi.divergence.metrics import Series, SeriesPoint

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "perf_change_set_a"

AS_A = datetime(2026, 9, 20, 9, tzinfo=UTC)
AS_B = datetime(2026, 7, 1, 9, tzinfo=UTC)
POINTS = 410


def _series(seed_text: str, as_of: datetime) -> Series:
    seed = sum(ord(c) for c in seed_text) + as_of.toordinal() % 89
    last = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC) - timedelta(days=1)
    out: Series = []
    for n in range(POINTS):
        t = last - timedelta(days=POINTS - 1 - n)
        if n % 53 == 52:
            out.append(SeriesPoint(t, None, "missing"))
            continue
        value = Decimal(1000 + seed) + Decimal(n) / 4 + Decimal((n * seed) % 31 - 15) * 3
        if n == POINTS - 1:
            value *= Decimal((seed % 7) - 2) or Decimal(3)  # a spike or a collapse today
        out.append(SeriesPoint(t, value, "ok" if n % 61 else "suspect"))
    return out


class FakeAdapters:
    """Any adapter method named by the metric registry returns a deterministic series."""

    def __init__(self) -> None:
        self.fetches: Counter[str] = Counter()

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)

        async def fetch(*args: Any) -> Series:
            subject = next((a for a in args if isinstance(a, str)), "")
            self.fetches[f"{name}:{subject}"] += 1
            as_of = next(a for a in args if isinstance(a, datetime))
            return _series(f"{name}:{subject}", as_of)

        return fetch


def make_service() -> AnomalyService:
    svc = AnomalyService(engine=object())
    svc.adapters = FakeAdapters()  # type: ignore[assignment]
    return svc


def dump(value: Any) -> str:
    return json.dumps(value, indent=1, default=str)


def _golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def reading_calls(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    calls: Counter[str] = Counter()
    for fn_name in ("current_reading", "duration", "quality_summary"):
        original = getattr(anomaly_metrics, fn_name)

        def wrapper(*args: Any, _orig: Any = original, _name: str = fn_name, **kw: Any) -> Any:
            calls[_name] += 1
            return _orig(*args, **kw)

        monkeypatch.setattr(anomaly_metrics, fn_name, wrapper)
    return calls


SCENARIOS: dict[str, tuple[str | None, datetime]] = {
    "btc_a": (None, AS_A),
    "eth_a": ("ETH", AS_A),
    "btc_b": ("BTC", AS_B),
}


@pytest.mark.parametrize("scenario", sorted(SCENARIOS))
async def test_scan_matches_golden_captured_from_unmodified_code(scenario: str) -> None:
    asset, as_of = SCENARIOS[scenario]
    out = await make_service().scan(asset=asset, as_of=as_of, knowledge_time=as_of)
    assert dump(out) == _golden(f"anomaly_scan_{scenario}.json")


async def test_scan_contradicting_evidence_is_complete_ordered_and_self_consistent() -> None:
    out = await make_service().scan(asset=None, as_of=AS_A, knowledge_time=AS_A)
    by_id = {a["metric_id"]: a for a in out["anomalies"]}
    assert list(by_id) == list(METRICS_BY_ID)
    for metric_id, anomaly in by_id.items():
        counterparts = METRICS_BY_ID[metric_id].counterparts
        evidence = anomaly["contradicting_evidence"]
        assert [e["metric_id"] for e in evidence] == list(counterparts)
        for e in evidence:
            assert e["band"] == by_id[e["metric_id"]]["band"]
            assert e["comparison"] == anomaly_metrics.compare_bands(anomaly["band"], e["band"])
    assert any(a["contradicting_evidence"] for a in out["anomalies"])


async def test_scan_computes_each_reading_once(reading_calls: Counter[str]) -> None:
    await make_service().scan(asset=None, as_of=AS_A, knowledge_time=AS_A)
    n_metrics = len(METRICS_BY_ID)
    assert n_metrics == 13
    assert dict(reading_calls) == {
        "current_reading": n_metrics,
        "duration": n_metrics,
        "quality_summary": n_metrics,
    }


async def test_separate_scans_do_not_share_readings(reading_calls: Counter[str]) -> None:
    svc = make_service()
    first = await svc.scan(asset=None, as_of=AS_A, knowledge_time=AS_A)
    second = await svc.scan(asset=None, as_of=AS_A, knowledge_time=AS_A)
    assert dump(first) == dump(second)
    assert reading_calls["current_reading"] == 2 * len(METRICS_BY_ID)


async def test_a_scan_for_another_asset_on_the_same_service_matches_a_fresh_service() -> None:
    svc = make_service()
    await svc.scan(asset="BTC", as_of=AS_A, knowledge_time=AS_A)
    eth = await svc.scan(asset="ETH", as_of=AS_A, knowledge_time=AS_A)
    assert dump(eth) == _golden("anomaly_scan_eth_a.json")


async def test_a_failing_scan_leaves_no_state_behind(
    monkeypatch: pytest.MonkeyPatch, reading_calls: Counter[str]
) -> None:
    svc = make_service()
    original = anomaly_metrics.duration
    state = {"n": 0}

    def flaky(*args: Any, **kw: Any) -> Any:
        state["n"] += 1
        if state["n"] == 6:
            raise RuntimeError("boom")
        return original(*args, **kw)

    monkeypatch.setattr(anomaly_metrics, "duration", flaky)
    with pytest.raises(RuntimeError, match="boom"):
        await svc.scan(asset=None, as_of=AS_A, knowledge_time=AS_A)
    monkeypatch.setattr(anomaly_metrics, "duration", original)
    reading_calls.clear()
    out = await svc.scan(asset=None, as_of=AS_A, knowledge_time=AS_A)
    assert dump(out) == _golden("anomaly_scan_btc_a.json")
    assert reading_calls["current_reading"] == len(METRICS_BY_ID)


async def test_detail_is_unchanged_and_does_not_memoise(reading_calls: Counter[str]) -> None:
    svc = make_service()
    out = await svc.detail(metric_id="etf_flows", asset=None, as_of=AS_A, knowledge_time=AS_A)
    assert dump(out) == _golden("anomaly_detail_etf_flows.json")
    counterparts = METRICS_BY_ID["etf_flows"].counterparts
    assert reading_calls["current_reading"] == 1 + len(counterparts)
