"""Unified Intelligence Snapshot (Phase 44; ADR-0081).

A pure, read-only projection of one stored ``ai.snapshot`` payload. See ``unified_snapshot``."""

from cfi.intelligence.confirmation import (
    ConfirmationInputError,
    build_confirmation,
)
from cfi.intelligence.unified_snapshot import (
    CONTRACT_VERSION,
    build_unified_snapshot,
)

__all__ = [
    "CONTRACT_VERSION",
    "ConfirmationInputError",
    "build_confirmation",
    "build_unified_snapshot",
]
