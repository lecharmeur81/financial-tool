"""Canonical observed-data record (L1) — the only shape provider data may take after normalisation.

Fields follow DATA_DICTIONARY.md §2 and CLAUDE.md R3. Invariants enforced here:
- all timestamps are timezone-aware and converted to UTC;
- a missing value is ``None`` **with** ``quality_status = missing`` — never zero, never silent;
- confidence, when given, is within [0, 1].
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from cfi.core.time import ensure_utc
from cfi.domain.enums import PitReliability, QualityStatus


@dataclass(frozen=True, slots=True)
class CanonicalObservation:
    dataset_id: str
    metric: str
    asset: str | None
    subject_ref: str
    period: str
    unit: str
    event_time: datetime
    available_at: datetime
    available_at_estimated: bool
    ingested_at: datetime
    value: Decimal | None
    source_provider: str
    original_source: str
    quality_status: QualityStatus
    pit_reliability: PitReliability
    revision: int = 0
    quality_note: str | None = None
    confidence: Decimal | None = None
    raw_ref: int | None = field(default=None)

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_time", ensure_utc(self.event_time, field="event_time"))
        object.__setattr__(
            self, "available_at", ensure_utc(self.available_at, field="available_at")
        )
        object.__setattr__(self, "ingested_at", ensure_utc(self.ingested_at, field="ingested_at"))

        if self.value is None and self.quality_status is not QualityStatus.MISSING:
            raise ValueError("value is None but quality_status is not 'missing' (R3)")
        if self.quality_status is QualityStatus.MISSING and self.value is not None:
            raise ValueError("quality_status is 'missing' but a value was provided")
        if self.quality_status is not QualityStatus.OK and not self.quality_note:
            raise ValueError("quality_note is required when quality_status is not 'ok'")
        if self.confidence is not None and not (Decimal(0) <= self.confidence <= Decimal(1)):
            raise ValueError("confidence must be within [0, 1]")
        if self.revision < 0:
            raise ValueError("revision must be >= 0")
        for name in ("dataset_id", "metric", "subject_ref", "period", "unit", "source_provider"):
            if not getattr(self, name):
                raise ValueError(f"{name} must not be empty")
        if not self.original_source:
            raise ValueError("original_source must not be empty (use 'unknown' if not provided)")
