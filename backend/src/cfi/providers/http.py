"""Shared HTTP client layer for every provider (ADR-0022, R8).

Gives each adapter, without per-adapter code: authentication (secret read from the environment,
never logged), timeouts, retries with exponential backoff and jitter (honouring ``Retry-After``),
a token-bucket rate limiter, a circuit breaker, and a record of every attempt.

Scope note: the rate limiter and circuit breaker are in-process. Background workers (ADR-0023)
will share them through Redis when several processes ingest in parallel.
"""

from __future__ import annotations

import asyncio
import os
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, Protocol

import httpx2

from cfi.core.errors import ProviderPermanentError, ProviderTransientError
from cfi.core.logging import get_logger
from cfi.core.time import utc_now
from cfi.domain.enums import AuthType
from cfi.providers.base import ProviderCapabilities, RawResponse, RequestSpec

log = get_logger(__name__)

REDACTED = "[REDACTED]"

Outcome = Literal[
    "success",
    "timeout",
    "connection_error",
    "rate_limited",
    "server_error",
    "auth_failed",
    "client_error",
    "circuit_open",
]

Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], float]


# --------------------------------------------------------------------------- request records


@dataclass(frozen=True, slots=True)
class RequestAttempt:
    """One HTTP attempt, successful or not — the basis of provider health and failure tracking."""

    provider_id: str
    dataset_id: str | None
    job_run_id: int | None
    endpoint: str
    attempt: int
    started_at: datetime
    latency_ms: float
    outcome: Outcome
    http_status: int | None
    error_class: str | None


class RequestRecorder(Protocol):
    async def record(self, attempt: RequestAttempt) -> None: ...


class ListRecorder:
    """Keeps attempts in memory (tests, and callers that persist later)."""

    def __init__(self) -> None:
        self.attempts: list[RequestAttempt] = []

    async def record(self, attempt: RequestAttempt) -> None:
        self.attempts.append(attempt)


# --------------------------------------------------------------------------- policies


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Exponential backoff: ``base * 2**(attempt-1)``, capped, with ± ``jitter`` fraction."""

    max_attempts: int = 4
    base_delay: float = 0.5
    max_delay: float = 30.0
    jitter: float = 0.1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if not 0 <= self.jitter < 1:
            raise ValueError("jitter must be in [0, 1)")

    def delay(
        self, attempt: int, retry_after: float | None = None, rng: random.Random | None = None
    ) -> float:
        backoff = min(self.max_delay, self.base_delay * (2.0 ** (attempt - 1)))
        if self.jitter:
            backoff *= 1 + (rng or random.Random()).uniform(-self.jitter, self.jitter)  # noqa: S311
        if retry_after is not None:
            backoff = max(backoff, retry_after)
        return min(backoff, self.max_delay)


class TokenBucket:
    """Token-bucket rate limiter. ``acquire`` waits (via ``sleep``) until a token is available."""

    def __init__(
        self,
        rate_per_second: float,
        capacity: int,
        *,
        clock: Clock = time.monotonic,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        if rate_per_second <= 0 or capacity < 1:
            raise ValueError("rate must be > 0 and capacity >= 1")
        self._rate = rate_per_second
        self._capacity = float(capacity)
        self._tokens = float(capacity)
        self._clock = clock
        self._sleep = sleep
        self._updated = clock()
        self._lock = asyncio.Lock()

    def _refill(self) -> None:
        now = self._clock()
        self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
        self._updated = now

    async def acquire(self) -> float:
        """Take one token; return how many seconds were spent waiting."""
        async with self._lock:
            waited = 0.0
            self._refill()
            while self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await self._sleep(wait)
                waited += wait
                self._refill()
            self._tokens -= 1
            return waited


CircuitState = Literal["closed", "open", "half_open"]


class CircuitBreaker:
    """Stops calling a failing provider for ``recovery_seconds`` after ``failure_threshold``
    consecutive transient failures, then lets one trial request through (half-open)."""

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_seconds: float = 60.0,
        *,
        clock: Clock = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_seconds = recovery_seconds
        self._clock = clock
        self._state: CircuitState = "closed"
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> CircuitState:
        if self._state == "open" and self._clock() - self._opened_at >= self.recovery_seconds:
            self._state = "half_open"
        return self._state

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        self._state = "closed"
        self._failures = 0

    def record_failure(self) -> None:
        self._failures += 1
        if self.state == "half_open" or self._failures >= self.failure_threshold:
            self._state = "open"
            self._opened_at = self._clock()


# --------------------------------------------------------------------------- client


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - utc_now()).total_seconds())


class ProviderHttpClient:
    """Sends an adapter's :class:`RequestSpec` with every R8 protection applied."""

    def __init__(
        self,
        capabilities: ProviderCapabilities,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
        retry: RetryPolicy | None = None,
        limiter: TokenBucket | None = None,
        breaker: CircuitBreaker | None = None,
        recorder: RequestRecorder | None = None,
        environ: Mapping[str, str] | None = None,
        sleep: Sleep = asyncio.sleep,
        clock: Clock = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.capabilities = capabilities
        self.retry = retry or RetryPolicy()
        self.limiter = limiter or TokenBucket(
            capabilities.rate_limit.rate, capabilities.rate_limit.requests, clock=clock, sleep=sleep
        )
        self.breaker = breaker or CircuitBreaker(clock=clock)
        self.recorder = recorder or ListRecorder()
        self._environ = environ if environ is not None else os.environ
        self._sleep = sleep
        self._clock = clock
        self._rng = rng
        self._client = httpx2.AsyncClient(
            base_url=capabilities.base_url,
            transport=transport,
            timeout=httpx2.Timeout(capabilities.timeout_seconds),
            follow_redirects=False,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> ProviderHttpClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ auth

    def _auth(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return (headers, extra query params) carrying the credential."""
        auth = self.capabilities.auth
        if auth.type is AuthType.NONE:
            return {}, {}
        secret = self._environ.get(auth.env_var)
        if not secret:
            raise ProviderPermanentError(
                f"Credential for provider '{self.capabilities.provider_id}' is not configured "
                f"(environment variable {auth.env_var}).",
                provider_id=self.capabilities.provider_id,
            )
        if auth.type is AuthType.API_KEY_QUERY:
            return {}, {auth.name: secret}
        if auth.type is AuthType.API_KEY_HEADER:
            return {auth.name: secret}, {}
        return {auth.name: f"Bearer {secret}"}, {}  # AuthType.BEARER

    def _redacted(
        self, params: Mapping[str, str], secret_params: Mapping[str, str]
    ) -> dict[str, str]:
        out = dict(params)
        for key in secret_params:
            out[key] = REDACTED
        return out

    # ------------------------------------------------------------------ send

    async def send(
        self, spec: RequestSpec, *, dataset_id: str | None = None, job_run_id: int | None = None
    ) -> RawResponse:
        provider_id = self.capabilities.provider_id
        last_error = "unknown"
        for attempt in range(1, self.retry.max_attempts + 1):
            started_at = utc_now()
            if not self.breaker.allow():
                await self._record(
                    spec,
                    dataset_id,
                    job_run_id,
                    attempt,
                    started_at,
                    0.0,
                    "circuit_open",
                    None,
                    None,
                )
                raise ProviderTransientError(
                    f"Provider '{provider_id}' is temporarily disabled after repeated failures "
                    "(circuit open).",
                    provider_id=provider_id,
                    outcome="circuit_open",
                )
            headers, secret_params = self._auth()
            await self.limiter.acquire()
            t0 = self._clock()
            retry_after: float | None = None
            try:
                response = await self._client.request(
                    spec.method,
                    spec.path,
                    params={**dict(spec.params), **secret_params},
                    headers=headers,
                )
            except httpx2.TimeoutException as exc:
                outcome: Outcome = "timeout"
                status: int | None = None
                error_class: str | None = type(exc).__name__
            except httpx2.TransportError as exc:
                outcome, status, error_class = "connection_error", None, type(exc).__name__
            else:
                status = response.status_code
                error_class = None
                if 200 <= status < 300:
                    latency = round((self._clock() - t0) * 1000, 2)
                    self.breaker.record_success()
                    await self._record(
                        spec,
                        dataset_id,
                        job_run_id,
                        attempt,
                        started_at,
                        latency,
                        "success",
                        status,
                        None,
                    )
                    return RawResponse(
                        provider_id=provider_id,
                        endpoint=spec.path,
                        request_params=self._redacted(spec.params, secret_params),
                        received_at=utc_now(),
                        status_code=status,
                        content_type=response.headers.get("content-type", ""),
                        body=response.content,
                    )
                if status == 429:
                    outcome = "rate_limited"
                    retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                elif status >= 500:
                    outcome = "server_error"
                    retry_after = _retry_after_seconds(response.headers.get("retry-after"))
                elif status in (401, 403):
                    outcome = "auth_failed"
                else:
                    outcome = "client_error"

            latency = round((self._clock() - t0) * 1000, 2)
            await self._record(
                spec,
                dataset_id,
                job_run_id,
                attempt,
                started_at,
                latency,
                outcome,
                status,
                error_class,
            )
            last_error = f"{outcome}" + (f" (HTTP {status})" if status else "")

            if outcome in ("auth_failed", "client_error"):
                raise ProviderPermanentError(
                    f"Provider '{provider_id}' rejected the request: {last_error}.",
                    provider_id=provider_id,
                    outcome=outcome,
                    http_status=status,
                )

            self.breaker.record_failure()
            if attempt < self.retry.max_attempts:
                delay = self.retry.delay(attempt, retry_after, self._rng)
                log.warning(
                    "provider_retry",
                    provider=provider_id,
                    endpoint=spec.path,
                    attempt=attempt,
                    outcome=outcome,
                    delay_s=round(delay, 3),
                )
                await self._sleep(delay)

        raise ProviderTransientError(
            f"Provider '{provider_id}' failed after {self.retry.max_attempts} attempts: "
            f"{last_error}.",
            provider_id=provider_id,
            outcome=last_error,
        )

    async def _record(
        self,
        spec: RequestSpec,
        dataset_id: str | None,
        job_run_id: int | None,
        attempt: int,
        started_at: datetime,
        latency_ms: float,
        outcome: Outcome,
        status: int | None,
        error_class: str | None,
    ) -> None:
        await self.recorder.record(
            RequestAttempt(
                provider_id=self.capabilities.provider_id,
                dataset_id=dataset_id,
                job_run_id=job_run_id,
                endpoint=spec.path,
                attempt=attempt,
                started_at=started_at,
                latency_ms=latency_ms,
                outcome=outcome,
                http_status=status,
                error_class=error_class,
            )
        )
