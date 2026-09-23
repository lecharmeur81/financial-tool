"""HTTP client layer: success, timeout, retry, backoff, rate limits, auth, circuit breaker."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from cfi.core.errors import ProviderPermanentError, ProviderTransientError
from cfi.domain.enums import AuthType
from cfi.providers.base import AuthSpec, FetchWindow, ProviderCapabilities, RequestSpec
from cfi.providers.http import (
    REDACTED,
    CircuitBreaker,
    ListRecorder,
    ProviderHttpClient,
    RetryPolicy,
    TokenBucket,
    _retry_after_seconds,
)
from cfi.providers.mock import (
    Fail,
    MockPoint,
    MockProviderA,
    MockProviderB,
    MockServerA,
    MockServerB,
    Timeout,
)
from tests.support import T0, FakeClock

POINTS = [MockPoint(T0 + timedelta(hours=i), Decimal("100") + i) for i in range(3)]
WINDOW = FetchWindow(T0, T0 + timedelta(hours=3))
NO_JITTER = RetryPolicy(max_attempts=3, base_delay=0.5, max_delay=30, jitter=0)


def _client(
    server: MockServerA | MockServerB,
    adapter: MockProviderA | MockProviderB,
    clock: FakeClock,
    *,
    retry: RetryPolicy = NO_JITTER,
    breaker: CircuitBreaker | None = None,
    environ: dict[str, str] | None = None,
) -> tuple[ProviderHttpClient, ListRecorder]:
    recorder = ListRecorder()
    client = ProviderHttpClient(
        adapter.capabilities,
        transport=server.transport(),
        retry=retry,
        breaker=breaker,
        recorder=recorder,
        environ=environ or {},
        sleep=clock.sleep,
        clock=clock,
    )
    return client, recorder


async def test_success_returns_raw_response_and_records_attempt() -> None:
    clock, adapter = FakeClock(), MockProviderA()
    client, recorder = _client(MockServerA(POINTS), adapter, clock)
    raw = await client.send(adapter.first_request("d", WINDOW), dataset_id="d", job_run_id=7)
    assert raw.status_code == 200
    assert raw.received_at.tzinfo is not None
    assert b'"data"' in raw.body
    assert [a.outcome for a in recorder.attempts] == ["success"]
    assert recorder.attempts[0].job_run_id == 7
    await client.aclose()


async def test_timeout_is_retried_with_exponential_backoff_then_fails() -> None:
    clock, adapter = FakeClock(), MockProviderA()
    server = MockServerA(POINTS).then(Timeout(), Timeout(), Timeout())
    client, recorder = _client(server, adapter, clock)
    with pytest.raises(ProviderTransientError, match="after 3 attempts: timeout"):
        await client.send(adapter.first_request("d", WINDOW))
    assert [a.outcome for a in recorder.attempts] == ["timeout"] * 3
    assert clock.slept == [0.5, 1.0]  # base * 2**(attempt-1); no sleep after the last attempt
    await client.aclose()


async def test_retry_recovers_after_server_errors() -> None:
    clock, adapter = FakeClock(), MockProviderA()
    server = MockServerA(POINTS).then(Fail(503), Fail(502))
    client, recorder = _client(server, adapter, clock)
    raw = await client.send(adapter.first_request("d", WINDOW))
    assert raw.status_code == 200
    assert [a.outcome for a in recorder.attempts] == ["server_error", "server_error", "success"]
    assert [a.http_status for a in recorder.attempts] == [503, 502, 200]
    await client.aclose()


async def test_rate_limited_response_honours_retry_after() -> None:
    clock, adapter = FakeClock(), MockProviderA()
    server = MockServerA(POINTS).then(Fail(429, {"Retry-After": "7"}))
    client, recorder = _client(server, adapter, clock)
    await client.send(adapter.first_request("d", WINDOW))
    assert [a.outcome for a in recorder.attempts] == ["rate_limited", "success"]
    assert clock.slept == [7.0]  # Retry-After (7 s) exceeds the backoff (0.5 s)
    await client.aclose()


async def test_client_errors_are_not_retried() -> None:
    clock, adapter = FakeClock(), MockProviderA()
    client, recorder = _client(MockServerA(POINTS).then(Fail(404)), adapter, clock)
    with pytest.raises(ProviderPermanentError, match="HTTP 404"):
        await client.send(adapter.first_request("d", WINDOW))
    assert [a.outcome for a in recorder.attempts] == ["client_error"]
    assert clock.slept == []
    await client.aclose()


async def test_token_bucket_spaces_out_requests() -> None:
    clock = FakeClock()
    bucket = TokenBucket(rate_per_second=2, capacity=1, clock=clock, sleep=clock.sleep)
    waits = [await bucket.acquire() for _ in range(3)]
    assert waits == [0.0, 0.5, 0.5]
    assert clock.slept == [0.5, 0.5]


async def test_api_key_header_is_sent_and_never_recorded() -> None:
    clock, adapter = FakeClock(), MockProviderB()
    server = MockServerB(POINTS, api_key="s3cret-value")
    env = {MockProviderB.API_KEY_ENV: "s3cret-value"}
    client, _ = _client(server, adapter, clock, environ=env)
    raw = await client.send(adapter.first_request("d", WINDOW))
    assert raw.status_code == 200
    assert server.requests[0].headers["X-API-Key"] == "s3cret-value"
    assert "s3cret-value" not in repr(raw.request_params)
    await client.aclose()


async def test_missing_credential_fails_before_any_request() -> None:
    clock, adapter = FakeClock(), MockProviderB()
    server = MockServerB(POINTS, api_key="k")
    client, recorder = _client(server, adapter, clock, environ={})
    with pytest.raises(ProviderPermanentError, match=MockProviderB.API_KEY_ENV):
        await client.send(adapter.first_request("d", WINDOW))
    assert server.requests == []
    assert recorder.attempts == []
    await client.aclose()


async def test_wrong_credential_is_a_permanent_auth_failure() -> None:
    clock, adapter = FakeClock(), MockProviderB()
    server = MockServerB(POINTS, api_key="right")
    client, recorder = _client(server, adapter, clock, environ={MockProviderB.API_KEY_ENV: "wrong"})
    with pytest.raises(ProviderPermanentError, match="auth_failed"):
        await client.send(adapter.first_request("d", WINDOW))
    assert [a.outcome for a in recorder.attempts] == ["auth_failed"]
    await client.aclose()


async def test_query_parameter_credentials_are_redacted() -> None:
    clock = FakeClock()
    caps = ProviderCapabilities(
        provider_id="q",
        display_name="q",
        base_url="https://mock-a.invalid",
        datasets=frozenset(),
        auth=AuthSpec(type=AuthType.API_KEY_QUERY, name="apikey", env_var="Q_KEY"),
    )
    server = MockServerA(POINTS)
    client = ProviderHttpClient(
        caps,
        transport=server.transport(),
        environ={"Q_KEY": "abc123"},
        sleep=clock.sleep,
        clock=clock,
    )
    spec = MockProviderA().first_request("d", WINDOW)
    raw = await client.send(RequestSpec(path=spec.path, params=spec.params))
    assert server.requests[0].url.params["apikey"] == "abc123"
    assert raw.request_params["apikey"] == REDACTED
    await client.aclose()


def _state(breaker: CircuitBreaker) -> str:
    return breaker.state  # read through a function: the state changes with the clock


async def test_circuit_breaker_opens_then_recovers() -> None:
    clock, adapter = FakeClock(), MockProviderA()
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=60, clock=clock)
    server = MockServerA(POINTS).then(Fail(500), Fail(500))
    client, recorder = _client(
        server, adapter, clock, retry=RetryPolicy(max_attempts=1, jitter=0), breaker=breaker
    )
    spec = adapter.first_request("d", WINDOW)
    for _ in range(2):
        with pytest.raises(ProviderTransientError):
            await client.send(spec)
    assert _state(breaker) == "open"
    with pytest.raises(ProviderTransientError, match="circuit open"):
        await client.send(spec)
    assert len(server.requests) == 2  # the open circuit made no request
    assert recorder.attempts[-1].outcome == "circuit_open"
    clock.advance(61)
    assert _state(breaker) == "half_open"
    await client.send(spec)  # trial request succeeds
    assert _state(breaker) == "closed"
    await client.aclose()


def test_retry_policy_delays() -> None:
    policy = RetryPolicy(base_delay=1, max_delay=5, jitter=0)
    assert [policy.delay(n) for n in (1, 2, 3, 4)] == [1, 2, 4, 5]
    assert policy.delay(1, retry_after=3) == 3
    assert policy.delay(1, retry_after=100) == 5  # capped


def test_retry_after_parsing() -> None:
    assert _retry_after_seconds("12") == 12
    assert _retry_after_seconds(None) is None
    assert _retry_after_seconds("not a date") is None
    assert _retry_after_seconds("Wed, 21 Oct 2015 07:28:00 GMT") == 0  # past date → no wait
