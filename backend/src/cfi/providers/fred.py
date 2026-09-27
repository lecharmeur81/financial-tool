"""FRED (Federal Reserve Economic Data, St. Louis Fed) — official keyed JSON API (Phase 11).

Verified 2026-09-27 against the official documentation
(``https://fred.stlouisfed.org/docs/api/fred/series_observations.html`` and
``https://fred.stlouisfed.org/docs/api/api_key.html``; the host itself, ``fred.stlouisfed.org``,
returns ``curl: (56) CONNECT tunnel failed, response 403`` from this sandboxed workspace's egress
proxy, so the shape below is confirmed from documentation, not a live payload — the same posture
already recorded for Blockchair, Binance and DefiLlama in earlier phases; real ingestion is
verified on the user's own first run):

- base URL ``https://api.stlouisfed.org/fred``; every request needs a free API key (register at
  https://fredaccount.stlouisfed.org/apikeys), sent as the query parameter ``api_key`` — unlike
  every other provider in this project except SoSoValue (Phase 6), this one is **not optional**:
  there is no free, keyless, officially documented route to the same data (the ``fredgraph.csv``
  download-button endpoint exists but is not a documented, versioned API — using it would mean
  building against an undocumented, unstable surface, which this project avoids by policy);
- ``GET /series/observations?series_id=&api_key=&file_type=json`` → ``{"observations": [{"date":
  "YYYY-MM-DD", "value": "123.4"}, ...], "count", "units", "observation_start",
  "observation_end", ...}``. Observations are sorted ascending by date by default. A missing
  observation is documented to come back as the literal string ``"."`` (FRED's own missing-value
  convention across every series), never omitted from the array — stored as
  ``QualityStatus.MISSING``, never silently dropped (R3);
- ``realtime_start`` / ``realtime_end`` (default: today) select which *vintage* of each value to
  return; left at their defaults here, so every value returned is FRED's **current** (most
  revised) figure for that date, not the value as first published — see
  ``cfi.macro.universe``'s "Point-in-time integrity" note for why this is an accepted limitation,
  not a bug;
- rate limit: **not officially published** by FRED (searched; no documented number found) — a
  conservative default is used here, exactly like SoSoValue's real limit (Phase 6), which was only
  discovered on the first live run; expect this to need adjustment then;
- request one series per call (the API's own model): every dataset below maps to exactly one FRED
  ``series_id`` (``cfi.macro.universe.FRED_SERIES``).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from cfi.core.errors import DataValidationError, ProviderNotConfiguredError
from cfi.domain.enums import AuthType, QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.macro.universe import FRED_SERIES, US_SUBJECT
from cfi.providers.base import (
    AuthSpec,
    FetchWindow,
    NormaliseContext,
    ProviderAdapter,
    ProviderCapabilities,
    ProviderRecord,
    RateLimitSpec,
    RawResponse,
    RequestSpec,
)
from cfi.providers.payload import load_json, schema_error, to_decimal

PROVIDER_ID = "fred"
API_KEY_ENV = "CFI_PROVIDER_FRED_API_KEY"
OBSERVATIONS_PATH = "/series/observations"
MISSING_VALUE = "."
_SERIES_TO_DATASET: dict[str, str] = {series: dataset for dataset, series in FRED_SERIES.items()}
ATTRIBUTION = {
    "text": "Data provided by FRED, Federal Reserve Bank of St. Louis",
    "url": "https://fred.stlouisfed.org",
}

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="FRED (Federal Reserve Bank of St. Louis)",
    base_url="https://api.stlouisfed.org/fred",
    datasets=frozenset(FRED_SERIES.keys()),
    auth=AuthSpec(AuthType.API_KEY_QUERY, "api_key", API_KEY_ENV, optional=False),
    rate_limit=RateLimitSpec(60, 60.0),
    timeout_seconds=15.0,
    max_pages=1,
    original_source="fred",
    terms_verified=False,
    notes=(
        "Federal Reserve Bank of St. Louis series (macroeconomic data, Phase 11). Requires a free "
        "API key (CFI_PROVIDER_FRED_API_KEY) — jobs are skipped, not failed, when it is not "
        "configured (same pattern as SoSoValue, Phase 6). Attribution required "
        "(https://fred.stlouisfed.org/legal/, 'FRED terms of use'). Values returned are FRED's "
        "current (most revised) vintage, not the value as first published — see "
        "cfi.macro.universe module docstring."
    ),
    gap_note="FRED returned '.' (its own missing-value marker) for this date",
)


class FRED(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        if dataset_id not in FRED_SERIES:
            raise ProviderNotConfiguredError(
                f"FRED: no series mapped for dataset {dataset_id!r}.", provider_id=PROVIDER_ID
            )
        series_id = FRED_SERIES[dataset_id]
        return RequestSpec(
            OBSERVATIONS_PATH,
            params={
                "series_id": series_id,
                "file_type": "json",
                "observation_start": window.start.date().isoformat(),
                "observation_end": window.end.date().isoformat(),
                "sort_order": "asc",
            },
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        return self.parse_page(RequestSpec(raw.endpoint, params=raw.request_params), raw)

    def parse_page(self, spec: RequestSpec, raw: RawResponse) -> Sequence[ProviderRecord]:
        data = load_json(raw)
        if not isinstance(data, dict) or not isinstance(data.get("observations"), list):
            raise schema_error(raw, "expected an object with an 'observations' list")
        series_id = spec.params.get("series_id")
        if series_id not in _SERIES_TO_DATASET:
            raise schema_error(raw, f"response for unknown series_id {series_id!r}")
        dataset_id = _SERIES_TO_DATASET[series_id]
        records = []
        for entry in data["observations"]:
            if not isinstance(entry, dict) or "date" not in entry or "value" not in entry:
                raise schema_error(raw, "each observation must have 'date' and 'value'")
            records.append(ProviderRecord(PROVIDER_ID, dataset_id, dict(entry)))
        return records

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        dataset = ctx.dataset
        p = record.payload
        date_str = str(p["date"])
        try:
            event_time = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        except ValueError as exc:
            raise DataValidationError(f"unparseable FRED observation date: {date_str!r}") from exc
        raw_value = p["value"]
        missing = raw_value == MISSING_VALUE
        value = None if missing else to_decimal(raw_value, "value")
        available_at, estimated = dataset.available_at(event_time, None, ctx.ingested_at)
        pit = dataset.pit_reliability(available_at, ctx.ingested_at)
        return CanonicalObservation(
            dataset_id=dataset.dataset_id,
            metric=dataset.metric,
            asset=US_SUBJECT,
            subject_ref=US_SUBJECT,
            venue=None,
            period=dataset.period,
            unit=dataset.unit,
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            value=value,
            source_provider=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            raw_ref=ctx.raw_ref,
            quality_status=QualityStatus.MISSING if missing else QualityStatus.OK,
            quality_note=CAPABILITIES.gap_note if missing else None,
            pit_reliability=pit,
            transformations=(
                "event_time: FRED observation date (YYYY-MM-DD) at UTC midnight; "
                "available_at estimated from the series' documented release schedule, not "
                "FRED's own realtime_start (current-vintage data only — see module docstring)",
            ),
        )
