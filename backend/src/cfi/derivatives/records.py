"""Small helpers shared by the derivatives adapters (canonical records, provider time stamps)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from cfi.core.errors import DataValidationError
from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.providers.base import NormaliseContext

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
PERCENT_TO_RATIO = "value: percent -> ratio (÷ 100)"


def epoch_ms(value: object, field: str) -> datetime:
    """Exact UTC time from epoch milliseconds given as an integer or a digit string."""
    if isinstance(value, bool):
        raise DataValidationError(f"{field} is not epoch milliseconds: {value!r}")
    if isinstance(value, int):
        number = value
    elif isinstance(value, str) and value.isdigit():
        number = int(value)
    else:
        raise DataValidationError(f"{field} is not epoch milliseconds: {value!r}")
    return EPOCH + timedelta(milliseconds=number)


def epoch_us(value: object, field: str) -> datetime:
    """Exact UTC time from epoch microseconds (integer)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise DataValidationError(f"{field} is not epoch microseconds: {value!r}")
    return EPOCH + timedelta(microseconds=value)


def ms(moment: datetime) -> str:
    """Epoch milliseconds of ``moment`` as a request parameter."""
    return str((moment - EPOCH) // timedelta(milliseconds=1))


def on_the_hour(moment: datetime, field: str) -> datetime:
    if (moment.minute, moment.second, moment.microsecond) != (0, 0, 0):
        raise DataValidationError(f"{field} {moment.isoformat()} is not on the hour")
    return moment


def scalar(
    ctx: NormaliseContext,
    *,
    provider_id: str,
    original_source: str,
    asset: str,
    subject_ref: str,
    venue: str,
    event_time: datetime,
    value: Decimal | None,
    published_at: datetime | None = None,
    transformations: tuple[str, ...] = (),
    quality: QualityStatus = QualityStatus.OK,
    note: str | None = None,
) -> CanonicalObservation:
    """A scalar derivatives observation; ``available_at`` follows the dataset rule."""
    spec = ctx.dataset
    available_at, estimated = spec.available_at(event_time, published_at, ctx.ingested_at)
    if value is None:
        quality = QualityStatus.MISSING
        note = note or "provider reported no value"
    return CanonicalObservation(
        dataset_id=spec.dataset_id,
        metric=spec.metric,
        asset=asset,
        subject_ref=subject_ref,
        venue=venue,
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
