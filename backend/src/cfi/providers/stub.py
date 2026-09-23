"""Stub provider — a placeholder that proves the interface, never a data source.

It supplies no datasets and refuses every call with ``ProviderNotConfiguredError``. It must never
return invented values (R3: never fabricate data).
"""

from __future__ import annotations

from collections.abc import Sequence

from cfi.core.errors import ProviderNotConfiguredError
from cfi.domain.observation import CanonicalObservation
from cfi.providers.base import (
    FetchWindow,
    NormaliseContext,
    ProviderAdapter,
    ProviderCapabilities,
    ProviderRecord,
    RawResponse,
    RequestSpec,
)


class StubProvider(ProviderAdapter):
    """A named placeholder for a provider that has not been integrated yet."""

    def __init__(self, provider_id: str = "stub", display_name: str = "Stub provider") -> None:
        self._capabilities = ProviderCapabilities(
            provider_id=provider_id,
            display_name=display_name,
            base_url="https://stub.invalid",
            datasets=frozenset(),
            notes="Placeholder only. No real data source is connected.",
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._capabilities

    def _refuse(self, action: str) -> ProviderNotConfiguredError:
        return ProviderNotConfiguredError(
            f"Provider '{self.provider_id}' is a stub and cannot {action}; "
            "no real data source is connected.",
            provider_id=self.provider_id,
        )

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        raise self._refuse(f"fetch dataset '{dataset_id}'")

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        raise self._refuse("parse responses")

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        raise self._refuse("normalise records")
