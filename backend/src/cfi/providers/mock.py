"""Mock providers and scriptable mock servers — FOR TESTS ONLY.

Values served here are synthetic test fixtures, not market data. These adapters are never registered
in the running application (R3: never fabricate data).

Two deliberately different provider styles exercise normalisation:

- ``MockProviderA``: epoch-millisecond timestamps, USD strings, cursor pagination, no auth.
- ``MockProviderB``: naive local timestamps in America/New_York, prices in US cents,
  page-number pagination, API-key header authentication.

The servers run in-process on ``httpx2.MockTransport`` and can be scripted to time out, rate-limit,
fail, or return malformed payloads.
"""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Self
from zoneinfo import ZoneInfo

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from cfi.core.errors import DataValidationError, SchemaMismatchError
from cfi.core.time import from_epoch, parse_timestamp
from cfi.domain.datasets import AvailabilityRule, DatasetSpec
from cfi.domain.enums import AuthType, PitReliability, QualityStatus
from cfi.domain.observation import CanonicalObservation
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

MOCK_DATASET = DatasetSpec(
    dataset_id="mock.close_price_1h",
    metric="close_price",
    unit="usd",
    period="1h",
    availability=AvailabilityRule("period_end_plus", timedelta(minutes=1)),
    freshness_limit=timedelta(hours=3),
    conflict_tolerance=Decimal("0.005"),
    revisable=False,
    expect_continuous=True,
    description="TEST FIXTURE: hourly close price served by mock providers.",
)


def _json(raw: RawResponse) -> Any:
    try:
        return json.loads(raw.body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise SchemaMismatchError(
            f"Malformed response from '{raw.provider_id}': body is not valid JSON.",
            provider_id=raw.provider_id,
        ) from exc


def _validate[M: BaseModel](model: type[M], data: Any, provider_id: str) -> M:
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in exc.errors()})
        raise SchemaMismatchError(
            f"Response from '{provider_id}' does not match the expected schema "
            f"(fields: {', '.join(fields)}).",
            provider_id=provider_id,
        ) from exc


def _decimal(value: str | int | None, provider_id: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation as exc:
        raise DataValidationError(f"non-numeric value {value!r}", provider_id=provider_id) from exc


# =========================================================================== provider A


class _RowA(BaseModel):
    model_config = ConfigDict(extra="ignore")
    t: int
    symbol: str
    close: str | None


class _PayloadA(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: list[_RowA]
    next_cursor: str | None = None


class MockProviderA(ProviderAdapter):
    SYMBOLS: Mapping[str, str] = {"BTCUSD": "BTC", "ETHUSD": "ETH"}

    def __init__(self, provider_id: str = "mock_a", symbol: str = "BTCUSD") -> None:
        self._symbol = symbol
        self._caps = ProviderCapabilities(
            provider_id=provider_id,
            display_name="Mock provider A (test fixture)",
            base_url="https://mock-a.invalid",
            datasets=frozenset({MOCK_DATASET.dataset_id}),
            rate_limit=RateLimitSpec(requests=10, per_seconds=1.0),
            timeout_seconds=2.0,
            original_source="mock_exchange_a",
            notes="Test fixture. Not a real data source.",
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._caps

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        return RequestSpec(
            path="/v1/prices",
            params={
                "symbol": self._symbol,
                "start_ms": str(int(window.start.timestamp() * 1000)),
                "end_ms": str(int(window.end.timestamp() * 1000)),
            },
        )

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        cursor = _validate(_PayloadA, _json(raw), self.provider_id).next_cursor
        if not cursor:
            return None
        return RequestSpec(
            path=previous.path, params={**previous.params, "cursor": cursor}, page=previous.page + 1
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        payload = _validate(_PayloadA, _json(raw), self.provider_id)
        return [
            ProviderRecord(self.provider_id, MOCK_DATASET.dataset_id, row.model_dump())
            for row in payload.data
        ]

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        row = record.payload
        asset = self.SYMBOLS.get(row["symbol"])
        if asset is None:
            raise DataValidationError(
                f"unknown symbol {row['symbol']!r}", provider_id=self.provider_id
            )
        event_time = from_epoch(row["t"], "ms")
        value = _decimal(row["close"], self.provider_id)
        available_at, estimated = ctx.dataset.available_at(event_time, None, ctx.ingested_at)
        missing = value is None
        return CanonicalObservation(
            dataset_id=ctx.dataset.dataset_id,
            metric=ctx.dataset.metric,
            asset=asset,
            subject_ref=f"{asset}-USD",
            period=ctx.dataset.period,
            unit="usd",
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            value=value,
            source_provider=self.provider_id,
            original_source=self._caps.original_source,
            quality_status=QualityStatus.MISSING if missing else QualityStatus.OK,
            quality_note="provider returned null for this point" if missing else None,
            pit_reliability=PitReliability.NATIVE,
            raw_ref=ctx.raw_ref,
            transformations=("event_time: epoch milliseconds -> UTC",),
        )


# =========================================================================== provider B


class _RowB(BaseModel):
    model_config = ConfigDict(extra="ignore")
    time: str
    ticker: str
    close_cents: int | None


class _PayloadB(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[_RowB]
    page: int
    pages: int


class MockProviderB(ProviderAdapter):
    TICKERS: Mapping[str, str] = {"XBT": "BTC", "ETH": "ETH"}
    SOURCE_TZ = "America/New_York"
    API_KEY_ENV = "CFI_PROVIDER_MOCK_B_API_KEY"

    def __init__(self, provider_id: str = "mock_b", ticker: str = "XBT") -> None:
        self._ticker = ticker
        self._caps = ProviderCapabilities(
            provider_id=provider_id,
            display_name="Mock provider B (test fixture)",
            base_url="https://mock-b.invalid",
            datasets=frozenset({MOCK_DATASET.dataset_id}),
            auth=AuthSpec(type=AuthType.API_KEY_HEADER, name="X-API-Key", env_var=self.API_KEY_ENV),
            rate_limit=RateLimitSpec(requests=5, per_seconds=1.0),
            timeout_seconds=2.0,
            original_source="mock_exchange_b",
            notes="Test fixture. Not a real data source.",
        )

    @property
    def capabilities(self) -> ProviderCapabilities:
        return self._caps

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        return RequestSpec(
            path="/quotes",
            params={
                "ticker": self._ticker,
                "from": window.start.isoformat(),
                "to": window.end.isoformat(),
                "page": "1",
            },
        )

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        payload = _validate(_PayloadB, _json(raw), self.provider_id)
        if payload.page >= payload.pages:
            return None
        return RequestSpec(
            path=previous.path,
            params={**previous.params, "page": str(payload.page + 1)},
            page=previous.page + 1,
        )

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        payload = _validate(_PayloadB, _json(raw), self.provider_id)
        return [
            ProviderRecord(self.provider_id, MOCK_DATASET.dataset_id, row.model_dump())
            for row in payload.items
        ]

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        row = record.payload
        asset = self.TICKERS.get(row["ticker"])
        if asset is None:
            raise DataValidationError(
                f"unknown ticker {row['ticker']!r}", provider_id=self.provider_id
            )
        try:
            event_time = parse_timestamp(row["time"], source_timezone=self.SOURCE_TZ)
        except ValueError as exc:
            raise DataValidationError(str(exc), provider_id=self.provider_id) from exc
        cents = _decimal(row["close_cents"], self.provider_id)
        value = None if cents is None else cents / Decimal(100)
        available_at, estimated = ctx.dataset.available_at(event_time, None, ctx.ingested_at)
        transformations = [f"event_time: naive {self.SOURCE_TZ} local time -> UTC"]
        if value is not None:
            transformations.append("value: US cents -> USD (divided by 100)")
        return CanonicalObservation(
            dataset_id=ctx.dataset.dataset_id,
            metric=ctx.dataset.metric,
            asset=asset,
            subject_ref=f"{asset}-USD",
            period=ctx.dataset.period,
            unit="usd",
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            ingested_at=ctx.ingested_at,
            value=value,
            source_provider=self.provider_id,
            original_source=self._caps.original_source,
            quality_status=QualityStatus.OK if value is not None else QualityStatus.MISSING,
            quality_note=None if value is not None else "provider returned null for this point",
            pit_reliability=PitReliability.NATIVE,
            raw_ref=ctx.raw_ref,
            transformations=tuple(transformations),
        )


# =========================================================================== mock servers


@dataclass(frozen=True, slots=True)
class Fail:
    status: int
    headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Timeout:
    pass


@dataclass(frozen=True, slots=True)
class RawBody:
    body: bytes
    status: int = 200


Action = Fail | Timeout | RawBody


@dataclass(frozen=True, slots=True)
class MockPoint:
    """One synthetic test point served by a mock server. ``value=None`` serves a JSON null."""

    time: datetime
    value: Decimal | None


class _MockServer:
    def __init__(self, points: Sequence[MockPoint], page_size: int = 2) -> None:
        self.points = sorted(points, key=lambda p: p.time)
        self.page_size = page_size
        self.script: deque[Action] = deque()
        self.requests: list[httpx2.Request] = []

    def then(self, *actions: Action) -> Self:
        """Queue actions served before normal data (one per request)."""
        self.script.extend(actions)
        return self

    def transport(self) -> httpx2.MockTransport:
        return httpx2.MockTransport(self._handle)

    async def _handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        if self.script:
            action = self.script.popleft()
            if isinstance(action, Timeout):
                raise httpx2.ReadTimeout("mock timeout", request=request)
            if isinstance(action, Fail):
                return httpx2.Response(
                    action.status, headers=dict(action.headers), json={"error": "x"}
                )
            return httpx2.Response(
                action.status, content=action.body, headers={"content-type": "application/json"}
            )
        return self._serve(request)

    def _serve(self, request: httpx2.Request) -> httpx2.Response:
        raise NotImplementedError

    def _window(self, start: datetime, end: datetime) -> list[MockPoint]:
        return [p for p in self.points if start <= p.time < end]


class MockServerA(_MockServer):
    def _serve(self, request: httpx2.Request) -> httpx2.Response:
        q = request.url.params
        start = datetime.fromtimestamp(int(q["start_ms"]) / 1000, tz=UTC)
        end = datetime.fromtimestamp(int(q["end_ms"]) / 1000, tz=UTC)
        points = self._window(start, end)
        offset = int(q.get("cursor", "0"))
        page = points[offset : offset + self.page_size]
        more = offset + self.page_size < len(points)
        return httpx2.Response(
            200,
            json={
                "data": [
                    {
                        "t": int(p.time.timestamp() * 1000),
                        "symbol": q["symbol"],
                        "close": None if p.value is None else str(p.value),
                    }
                    for p in page
                ],
                "next_cursor": str(offset + self.page_size) if more else None,
            },
        )


class MockServerB(_MockServer):
    def __init__(self, points: Sequence[MockPoint], page_size: int = 2, api_key: str = "") -> None:
        super().__init__(points, page_size)
        self.api_key = api_key

    def _serve(self, request: httpx2.Request) -> httpx2.Response:
        if self.api_key and request.headers.get("X-API-Key") != self.api_key:
            return httpx2.Response(401, json={"error": "unauthorised"})
        q = request.url.params
        points = self._window(datetime.fromisoformat(q["from"]), datetime.fromisoformat(q["to"]))
        pages = max(1, -(-len(points) // self.page_size))
        page_no = int(q.get("page", "1"))
        page = points[(page_no - 1) * self.page_size : page_no * self.page_size]
        ny = ZoneInfo(MockProviderB.SOURCE_TZ)
        return httpx2.Response(
            200,
            json={
                "items": [
                    {
                        "time": p.time.astimezone(ny).replace(tzinfo=None).isoformat(sep=" "),
                        "ticker": q["ticker"],
                        "close_cents": None if p.value is None else int(p.value * 100),
                    }
                    for p in page
                ],
                "page": page_no,
                "pages": pages,
            },
        )
