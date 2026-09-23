"""Provider adapter interface (ADR-0022, R8).

An adapter is the *only* place provider-specific symbols, field names, units and time
conventions exist.
Everything it returns from :meth:`ProviderAdapter.normalise` is a :class:`CanonicalObservation`.

Resilience (timeouts, retries with exponential backoff, rate limits, circuit breaking, payload
archiving, request ledger) belongs to the shared HTTP client layer planned for the ingestion
phase — adapters stay small and contain mapping logic only.

**No real provider is connected in Phase 3.**
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cfi.core.time import ensure_utc
from cfi.domain.enums import AuthType
from cfi.domain.observation import CanonicalObservation


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """What a provider can supply — declared, then verified against real documentation."""

    provider_id: str
    display_name: str
    datasets: frozenset[str]
    auth_type: AuthType
    terms_verified: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class FetchWindow:
    """Half-open UTC time window [start, end)."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "start", ensure_utc(self.start, field="start"))
        object.__setattr__(self, "end", ensure_utc(self.end, field="end"))
        if self.start >= self.end:
            raise ValueError("FetchWindow.start must be earlier than FetchWindow.end")


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


class ProviderAdapter(ABC):
    """Interface every provider adapter implements."""

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declared capabilities of this provider."""

    @abstractmethod
    async def fetch(self, dataset_id: str, window: FetchWindow) -> RawResponse:
        """Fetch raw data for ``dataset_id`` in ``window``. Must not transform the payload."""

    @abstractmethod
    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        """Parse a raw response. Raise ``SchemaMismatchError`` if its shape is unexpected."""

    @abstractmethod
    def normalise(self, record: ProviderRecord, ingested_at: datetime) -> CanonicalObservation:
        """Convert one provider record into the canonical model (units, symbols, UTC)."""

    @property
    def provider_id(self) -> str:
        return self.capabilities.provider_id

    def supports(self, dataset_id: str) -> bool:
        return dataset_id in self.capabilities.datasets
