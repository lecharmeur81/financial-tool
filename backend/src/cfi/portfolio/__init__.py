"""Portfolio intelligence (Phase 54, step 1): a read-only exposure view of SIMULATED paper trades.

Nothing here is a real holding. See ``exposure``."""

from cfi.portfolio.exposure import (
    CONTRACT_VERSION,
    NOT_CLAIMED,
    UNAVAILABLE,
    build_exposure,
    summarize_brief,
)

__all__ = ["CONTRACT_VERSION", "NOT_CLAIMED", "UNAVAILABLE", "build_exposure", "summarize_brief"]
