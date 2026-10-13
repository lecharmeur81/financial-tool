"""``RotationService.matrix``: the full output is pinned to a golden captured from the unmodified
code, and each node's reading is computed once per matrix (not once per pair).

The adapters are a deterministic in-memory fake (synthetic series with trends, wobble and gaps),
so these tests exercise the real service, real metric functions and real classification, and never
touch a database. They prove behavioural identity of the memoisation; they say nothing about
production data volumes or runtime.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from cfi.divergence.metrics import Series, SeriesPoint
from cfi.rotation.service import _MATRIX_ELIGIBLE, RotationService
from cfi.rotation.universe import EXCLUDED_PAIRS, NODES_BY_ID

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "perf_change_set_a"

AS_A = datetime(2026, 9, 20, 9, tzinfo=UTC)
AS_B = datetime(2026, 7, 1, 9, tzinfo=UTC)
WINDOW = 30
POINTS = 430


def _series(
    name: str, as_of: datetime, *, base: str, drift: str, wobble: str, signed: bool = False
) -> Series:
    """Deterministic synthetic daily series that only contains points at or before ``as_of``."""
    seed = sum(ord(c) for c in name) + 3 + as_of.toordinal() % 97
    last = datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC) - timedelta(days=1)
    out: Series = []
    for n in range(POINTS):
        t = last - timedelta(days=POINTS - 1 - n)
        if n % 41 == 40:
            out.append(SeriesPoint(t, None, "missing"))
            continue
        noise = Decimal((n * seed) % 23 - 11) * Decimal(wobble)
        value = Decimal(base) + Decimal(drift) * n + noise
        if signed:
            value = value if (n // 9) % 2 == 0 else -value
        out.append(SeriesPoint(t, value, "ok"))
    return out


@dataclass
class FakeAdapters:
    fetches: Counter[str]

    async def total_market_cap(self, as_of: datetime, knowledge_time: datetime) -> Series:
        self.fetches["total_market_cap"] += 1
        return _series(
            "total", as_of, base="3000000000000", drift="2000000000", wobble="10000000000"
        )

    async def asset_market_cap(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> Series:
        self.fetches[f"asset_market_cap:{asset}"] += 1
        table = {
            "BTC": ("1800000000000", "1100000000", "9000000000"),
            "ETH": ("400000000000", "-300000000", "4000000000"),
            "SOL": ("90000000000", "400000000", "2500000000"),
            "XRP": ("140000000000", "-100000000", "3000000000"),
        }
        base, drift, wobble = table[asset]
        return _series(asset, as_of, base=base, drift=drift, wobble=wobble)

    async def stablecoin_supply(
        self, subject: str, as_of: datetime, knowledge_time: datetime
    ) -> Series:
        self.fetches[f"stablecoin_supply:{subject}"] += 1
        table = {
            "TOTAL": ("250000000000", "150000000", "700000000"),
            "USDT": ("120000000000", "-60000000", "500000000"),
            "USDC": ("50000000000", "90000000", "400000000"),
        }
        base, drift, wobble = table.get(subject, ("1000000000", "1000000", "100000"))
        return _series(subject, as_of, base=base, drift=drift, wobble=wobble)

    async def retail_meme_trending_count(self, as_of: datetime, knowledge_time: datetime) -> Series:
        self.fetches["retail_meme_trending"] += 1
        return _series("meme", as_of, base="5", drift="0.01", wobble="0.3")

    async def institutional_net_flow(
        self, asset: str, as_of: datetime, knowledge_time: datetime
    ) -> Series:
        self.fetches[f"institutional_net_flow:{asset}"] += 1
        return _series(
            f"inst{asset}", as_of, base="1000000", drift="1000", wobble="200000", signed=True
        )

    async def whale_net_flow(self, asset: str, as_of: datetime, knowledge_time: datetime) -> Series:
        self.fetches[f"whale_net_flow:{asset}"] += 1
        return _series(
            f"whale{asset}", as_of, base="500000", drift="-500", wobble="150000", signed=True
        )


def make_service() -> RotationService:
    svc = RotationService(engine=object())
    svc.adapters = FakeAdapters(Counter())  # type: ignore[assignment]
    return svc


def dump(value: Any) -> str:
    return json.dumps(value, indent=1, default=str)


def _golden(name: str) -> str:
    return (GOLDEN_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def node_series_calls(monkeypatch: pytest.MonkeyPatch) -> Counter[str]:
    calls: Counter[str] = Counter()
    original = RotationService._node_series

    async def counting(self: RotationService, node: Any, as_of: datetime, kt: datetime) -> Any:
        calls[node.node_id] += 1
        return await original(self, node, as_of, kt)

    monkeypatch.setattr(RotationService, "_node_series", counting)
    return calls


@pytest.mark.parametrize(("label", "as_of"), [("a", AS_A), ("b", AS_B)])
async def test_matrix_matches_golden_captured_from_unmodified_code(
    label: str, as_of: datetime
) -> None:
    out = await make_service().matrix(window_days=WINDOW, as_of=as_of, knowledge_time=as_of)
    text = dump(out)
    assert "_rolling" not in text
    assert text == _golden(f"rotation_matrix_{label}.json")


async def test_every_pair_keeps_its_duration_and_episode_fields() -> None:
    """Guards the ``pop('_rolling')`` hazard: a reused reading that lost its rolling series would
    silently turn ``duration`` into ``None`` for every pair after the first."""
    out = await make_service().matrix(window_days=WINDOW, as_of=AS_A, knowledge_time=AS_A)
    pairs = out["pairs"]
    assert len(pairs) == 22
    for p in pairs:
        both_available = (
            p["from_node"]["status"] != "unavailable" and p["to_node"]["status"] != "unavailable"
        )
        assert both_available
        assert p["duration"] is not None
        assert set(p["duration"]) == {"days", "capped", "since"}
        assert "_rolling" not in p["from_node"]
        assert "_rolling" not in p["to_node"]
    assert any(p["historical_examples"] for p in pairs)
    assert any(p["inferred_capital_rotation"]["status"] == "possible_rotation" for p in pairs)


async def test_each_node_series_is_computed_once_per_matrix(
    node_series_calls: Counter[str],
) -> None:
    await make_service().matrix(window_days=WINDOW, as_of=AS_A, knowledge_time=AS_A)
    assert set(node_series_calls) == set(_MATRIX_ELIGIBLE)
    assert dict(node_series_calls) == {node_id: 1 for node_id in _MATRIX_ELIGIBLE}


async def test_matrix_calls_do_not_reuse_stale_readings() -> None:
    svc = make_service()
    first = await svc.matrix(window_days=WINDOW, as_of=AS_A, knowledge_time=AS_A)
    second = await svc.matrix(window_days=WINDOW, as_of=AS_B, knowledge_time=AS_B)
    assert dump(second) == _golden("rotation_matrix_b.json")
    assert dump(second) == dump(
        await make_service().matrix(window_days=WINDOW, as_of=AS_B, knowledge_time=AS_B)
    )
    again = await svc.matrix(window_days=WINDOW, as_of=AS_A, knowledge_time=AS_A)
    assert dump(again) == dump(first)


async def test_different_window_days_are_not_mixed_within_one_service() -> None:
    svc = make_service()
    w30 = await svc.matrix(window_days=30, as_of=AS_A, knowledge_time=AS_A)
    w7 = await svc.matrix(window_days=7, as_of=AS_A, knowledge_time=AS_A)
    assert dump(w7) == dump(
        await make_service().matrix(window_days=7, as_of=AS_A, knowledge_time=AS_A)
    )
    assert dump(w30) != dump(w7)


async def test_matrix_output_does_not_share_mutable_objects_between_pairs() -> None:
    out = await make_service().matrix(window_days=WINDOW, as_of=AS_A, knowledge_time=AS_A)
    seen: dict[str, dict[str, Any]] = {}
    for p in out["pairs"]:
        for side in ("from_node", "to_node"):
            reading = p[side]
            node_id = reading["node_id"]
            if node_id in seen:
                other = seen[node_id]
                assert reading is not other
                assert reading["historical_percentile"] is not other["historical_percentile"]
                assert reading["data_quality"] is not other["data_quality"]
            else:
                seen[node_id] = reading


async def test_direct_pair_calls_are_unchanged_and_repeatable(
    node_series_calls: Counter[str],
) -> None:
    svc = make_service()
    first = await svc.pair(
        from_node_id="btc",
        to_node_id="eth",
        window_days=WINDOW,
        as_of=AS_A,
        knowledge_time=AS_A,
    )
    assert dump(first) == _golden("rotation_pair_btc_eth.json")
    assert dict(node_series_calls) == {"btc": 1, "eth": 1}
    second = await svc.pair(
        from_node_id="btc",
        to_node_id="eth",
        window_days=WINDOW,
        as_of=AS_A,
        knowledge_time=AS_A,
    )
    assert dump(second) == dump(first)
    # a direct pair call recomputes both readings every time (no memo outside ``matrix``)
    assert dict(node_series_calls) == {"btc": 2, "eth": 2}


async def test_direct_pair_after_a_matrix_does_not_use_matrix_readings(
    node_series_calls: Counter[str],
) -> None:
    svc = make_service()
    await svc.matrix(window_days=WINDOW, as_of=AS_A, knowledge_time=AS_A)
    node_series_calls.clear()
    out = await svc.pair(
        from_node_id="btc",
        to_node_id="eth",
        window_days=WINDOW,
        as_of=AS_A,
        knowledge_time=AS_A,
    )
    assert dump(out) == _golden("rotation_pair_btc_eth.json")
    assert dict(node_series_calls) == {"btc": 1, "eth": 1}


async def test_failure_inside_matrix_leaves_no_state_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc = make_service()
    original = RotationService._node_series
    state = {"n": 0}

    async def flaky(self: RotationService, node: Any, as_of: datetime, kt: datetime) -> Any:
        state["n"] += 1
        if state["n"] == 5:
            raise RuntimeError("boom")
        return await original(self, node, as_of, kt)

    monkeypatch.setattr(RotationService, "_node_series", flaky)
    with pytest.raises(RuntimeError, match="boom"):
        await svc.matrix(window_days=WINDOW, as_of=AS_A, knowledge_time=AS_A)
    monkeypatch.setattr(RotationService, "_node_series", original)
    out = await svc.matrix(window_days=WINDOW, as_of=AS_A, knowledge_time=AS_A)
    assert dump(out) == _golden("rotation_matrix_a.json")


def test_fixture_covers_all_matrix_eligible_nodes() -> None:
    assert len(_MATRIX_ELIGIBLE) == 8
    assert all(n in NODES_BY_ID for n in _MATRIX_ELIGIBLE)
    assert EXCLUDED_PAIRS  # the 22 pairs are 28 combinations minus exclusions
