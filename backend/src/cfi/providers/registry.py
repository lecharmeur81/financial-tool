"""Provider registry — looks adapters up by ID.

Unknown providers are an explicit error, never a silent fallback.
"""

from __future__ import annotations

from cfi.core.errors import ProviderNotConfiguredError
from cfi.providers.base import ProviderAdapter


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        provider_id = adapter.provider_id
        if provider_id in self._providers:
            raise ValueError(f"provider '{provider_id}' is already registered")
        self._providers[provider_id] = adapter

    def get(self, provider_id: str) -> ProviderAdapter:
        try:
            return self._providers[provider_id]
        except KeyError:
            raise ProviderNotConfiguredError(
                f"Provider '{provider_id}' is not registered.", provider_id=provider_id
            ) from None

    def providers_for(self, dataset_id: str) -> list[ProviderAdapter]:
        """Adapters declaring support for ``dataset_id``.

        Priority between them is decided by the dataset registry, not here.
        """
        return [p for p in self._providers.values() if p.supports(dataset_id)]

    def ids(self) -> list[str]:
        return sorted(self._providers)
