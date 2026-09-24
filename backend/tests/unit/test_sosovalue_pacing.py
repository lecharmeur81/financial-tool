"""SoSoValue request pacing, from the first real run (2026-09-24): HTTP 429 "wait 58 s" after 10
back-to-back requests. Requests are now evenly spaced and such a wait is honoured, not fatal."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx2
import pytest

from cfi.core.errors import ProviderTransientError
from cfi.institutional.universe import ETF_FLOW_US_SPOT
from cfi.providers.base import FetchWindow, RateLimitSpec
from cfi.providers.http import ListRecorder, ProviderHttpClient, RetryPolicy
from cfi.providers.sosovalue import API_KEY_ENV, CAPABILITIES, SoSoValue
from tests.institutional_fakes import SoSoValueFake
from tests.support import FakeClock

NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)
SPEC = SoSoValue().first_request(
    ETF_FLOW_US_SPOT.dataset_id, FetchWindow(NOW - timedelta(days=31), NOW, "BTC")
)


def client(fake: SoSoValueFake, clock: FakeClock) -> tuple[ProviderHttpClient, ListRecorder]:
    recorder = ListRecorder()
    c = ProviderHttpClient(
        CAPABILITIES,
        transport=fake.transport(),
        retry=RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=30, jitter=0),
        recorder=recorder,
        environ={API_KEY_ENV: "test-key"},
        sleep=clock.sleep,
        clock=clock,
    )
    return c, recorder


def too_many(wait: int) -> httpx2.Response:
    return httpx2.Response(
        429,
        json={"code": 402901, "message": "Rate limit exceeded", "retry_after": wait},
        headers={"retry-after": str(wait)},
    )


def test_declared_pacing_is_even_without_bursts() -> None:
    assert CAPABILITIES.rate_limit == RateLimitSpec(8, 60.0, burst=1)
    assert CAPABILITIES.rate_limit.capacity == 1
    assert RateLimitSpec(5, 60.0).capacity == 5  # other providers keep a full bucket


async def test_requests_are_spaced_seven_and_a_half_seconds_apart() -> None:
    clock = FakeClock()
    c, _ = client(SoSoValueFake(), clock)
    for _ in range(3):
        await c.send(SPEC)
    assert clock.slept == pytest.approx([7.5, 7.5])
    await c.aclose()


async def test_a_58_second_wait_is_honoured_then_retried() -> None:
    clock = FakeClock()
    fake = SoSoValueFake()
    fake.script.append(too_many(58))
    c, recorder = client(fake, clock)
    raw = await c.send(SPEC)
    assert raw.status_code == 200
    assert [a.outcome for a in recorder.attempts] == ["rate_limited", "success"]
    assert 58 in clock.slept  # never retried earlier than asked
    await c.aclose()


async def test_a_wait_beyond_90_seconds_fails_and_holds_the_circuit() -> None:
    clock = FakeClock()
    fake = SoSoValueFake()
    fake.script.append(too_many(120))
    c, recorder = client(fake, clock)
    with pytest.raises(ProviderTransientError, match="wait 120 s"):
        await c.send(SPEC)
    with pytest.raises(ProviderTransientError, match="circuit open"):
        await c.send(SPEC)
    assert [a.outcome for a in recorder.attempts] == ["rate_limited", "circuit_open"]
    await c.aclose()
