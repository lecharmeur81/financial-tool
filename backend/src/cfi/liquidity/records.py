"""Small helpers shared by the liquidity adapter (canonical records, DefiLlama's date format)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.core.errors import DataValidationError
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.providers.base import NormaliseContext

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def epoch_seconds(value: object, field: str) -> datetime:
    """Exact UTC time from epoch seconds given as an integer or a digit string (DefiLlama's
    ``date`` field is a digit string, e.g. ``"1511913600"``)."""
    if isinstance(value, bool):
        raise DataValidationError(f"{field} is not epoch seconds: {value!r}")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    else:
        raise DataValidationError(f"{field} is not epoch seconds: {value!r}")
    return EPOCH + timedelta(seconds=number)


def scalar(
    ctx: NormaliseContext,
    *,
    provider_id: str,
    original_source: str,
    asset: str,
    subject_ref: str,
    event_time: datetime,
    value: Decimal | None,
    transformations: tuple[str, ...] = (),
    quality: QualityStatus = QualityStatus.OK,
    note: str | None = None,
) -> CanonicalObservation:
    """A scalar liquidity observation; ``available_at`` follows the dataset rule."""
    spec = ctx.dataset
    available_at, estimated = spec.available_at(event_time, None, ctx.ingested_at)
    if value is None:
        quality = QualityStatus.MISSING
        note = note or "provider reported no value"
    return CanonicalObservation(
        dataset_id=spec.dataset_id,
        metric=spec.metric,
        asset=asset,
        subject_ref=subject_ref,
        venue=provider_id,
        period=spec.period,
        unit=spec.unit,
        event_time=event_time,
        available_at=available_at,
        available_at_estimated=estimated,
        ingested_at=ctx.ingested_at,
        value=value,
        source_provider=provider_id,
        original_source=original_source,
        raw_ref=ctx.raw_ref,
        quality_status=quality,
        quality_note=note,
        pit_reliability=spec.pit_reliability(available_at, ctx.ingested_at),
        transformations=transformations,
    )
