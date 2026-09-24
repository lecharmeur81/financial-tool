"""Provider adapter interface (ADR-0022, R8).

An adapter is the *only* place provider-specific symbols, field names, units and time
conventions exist. It is deliberately small:

- ``first_request`` / ``next_request`` describe *what* to ask for (including pagination);
- ``parse`` validates the payload shape and raises ``SchemaMismatchError`` if it changed;
- ``normalise`` converts one provider record into a canonical record
  (:class:`CanonicalObservation` or :class:`CanonicalBar`).

*How* requests are sent — authentication, timeouts, retries with exponential backoff, rate
limits, circuit breaking, request logging — is handled once, in :mod:`cfi.providers.http`.
Storage, duplicate/missing/stale/conflict detection and provenance are handled by
:mod:`cfi.ingestion`. Adapters never touch the database.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from cfi.core.time import ensure_utc
from cfi.domain.datasets import DatasetSpec
from cfi.domain.enums import AuthType
from cfi.domain.observation import ObservedRecord


@dataclass(frozen=True, slots=True)
class AuthSpec:
    """How a provider authenticates. The secret is read from ``env_var`` at request time."""

    type: AuthType = AuthType.NONE
    name: str = ""  # header or query-parameter name
    env_var: str = ""  # environment variable holding the secret (never the secret itself)
    optional: bool = False  # True: send the request without credential when none is configured

    def __post_init__(self) -> None:
        if self.type is not AuthType.NONE and not (self.name and self.env_var):
            raise ValueError("authenticated providers need both 'name' and 'env_var'")


@dataclass(frozen=True, slots=True)
class RateLimitSpec:
    """Provider limit expressed as ``requests`` per ``per_seconds`` (token bucket)."""

    requests: int
    per_seconds: float
    # Largest burst sent back to back. Default: ``requests`` (a full bucket). Providers that count
    # requests in fixed windows need a small burst, or two bursts can land in one window.
    burst: int | None = None

    def __post_init__(self) -> None:
        if self.requests <= 0 or self.per_seconds <= 0:
            raise ValueError("rate limit must be positive")
        if self.burst is not None and self.burst < 1:
            raise ValueError("burst must be >= 1")

    @property
    def capacity(self) -> int:
        return self.burst if self.burst is not None else self.requests

    @property
    def rate(self) -> float:
        return self.requests / self.per_seconds


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a provider can supply and how to call it — declared, then verified against real docs."""

    provider_id: str
    display_name: str
    base_url: str
    datasets: frozenset[str]
    auth: AuthSpec = field(default_factory=AuthSpec)
    rate_limit: RateLimitSpec = field(default_factory=lambda: RateLimitSpec(1, 1.0))
    timeout_seconds: float = 10.0
    max_pages: int = 1000
    original_source: str = "unknown"
    terms_verified: bool = False
    notes: str = ""
    # How to describe an expected-but-absent point from this provider (explicit missing rows).
    gap_note: str = "expected point not delivered by provider"
    # Longest provider-requested wait (Retry-After) the client honours and then retries. None: the
    # retry policy's maximum delay. Longer requests fail the call and hold the circuit open.
    max_retry_wait_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class FetchWindow:
    """Half-open UTC time window [start, end), optionally for one canonical subject.

    ``subject`` is a canonical asset symbol (e.g. ``BTC``); ``None`` means every subject the
    adapter covers for the dataset.
    """

    start: datetime
    end: datetime
    subject: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", ensure_utc(self.start, field="start"))
        object.__setattr__(self, "end", ensure_utc(self.end, field="end"))
        if self.start >= self.end:
            raise ValueError("FetchWindow.start must be earlier than FetchWindow.end")

    @property
    def length(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True, slots=True)
class RequestSpec:
    """One HTTP request an adapter wants sent. ``params`` must not contain secrets."""

    path: str
    params: Mapping[str, str] = field(default_factory=dict)
    method: Literal["GET", "POST"] = "GET"
    page: int = 1
    # Adapter bookkeeping for pagination (e.g. the overall window end). Never sent to the provider.
    state: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RawResponse:
    """An unmodified provider response (L0)."""

    provider_id: str
    endpoint: str
    request_params: Mapping[str, str]
    received_at: datetime
    status_code: int
    content_type: str
    body: bytes

    def __post_init__(self) -> None:
        object.__setattr__(self, "received_at", ensure_utc(self.received_at, field="received_at"))


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    """One provider-shaped record parsed from a raw response (not yet canonical)."""

    provider_id: str
    dataset_id: str
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class NormaliseContext:
    """What an adapter needs to build canonical records."""

    dataset: DatasetSpec
    ingested_at: datetime
    raw_ref: int | None


class ProviderAdapter(ABC):
    """Interface every provider adapter implements."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declared capabilities of this provider."""

    @abstractmethod
    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        """The first (or only) request for ``dataset_id`` over ``window``."""

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        """The next page, or ``None`` when done. Default: no pagination."""
        return None

    @abstractmethod
    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        """Validate and split a raw response. Raise ``SchemaMismatchError`` on unexpected shape."""

    def parse_page(self, spec: RequestSpec, raw: RawResponse) -> Sequence[ProviderRecord]:
        """Parse one page, with the request that produced it. Default: :meth:`parse`.

        Override when records need context carried in ``spec.state`` (e.g. the fund names read
        from a listing page earlier in the same run)."""
        return self.parse(raw)

    @abstractmethod
    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> ObservedRecord:
        """Convert one provider record into the canonical model (units, symbols, UTC).

        Raise ``DataValidationError`` for a record that cannot be normalised; the engine rejects
        that record, records why, and continues with the others. Raise ``NotYetFinalError`` for a
        record that is not final yet (e.g. the current, unfinished bar): it is skipped and counted.
        """

    @property
    def provider_id(self) -> str:
        return self.capabilities.provider_id

    def supports(self, dataset_id: str) -> bool:
        return dataset_id in self.capabilities.datasets
