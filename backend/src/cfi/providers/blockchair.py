"""Blockchair API — large transfers, top-address balances and Bitcoin coin-age aggregations.

Verified 2026-09-24 against the official documentation (API.md in github.com/Blockchair/
Blockchair.Support, API v2). No live response could be captured from this development environment
(the API host is not reachable from it); every shape below is the documented one, and the first
real run will be checked against it (a changed shape fails the run with a schema error).

- base URL ``https://api.blockchair.com``; without a key: personal / non-commercial use up to
  1,440 requests a day, hard limit 30 requests a minute; errors 402 / 429 / 435 / 436 / 437 when a
  limit is exceeded, 430 / 434 / 503 when the IP address is blocked. An optional key goes in the
  ``key`` query parameter (``CFI_PROVIDER_BLOCKCHAIR_API_KEY``);
- responses: ``{"data": [...], "context": {"code": 200, "limit", "offset", "rows",
  "total_rows", "state", "request_cost", ...}}``; ``request_cost`` is counted against the daily
  limit (table base cost 2 / 5 / 10 + 1 per filter + 10 per aggregation, × 1.9 for 100 rows);
- query language: ``?q=column(a..b)`` (inclusive; timestamps ``YYYY-MM-DD HH:ii:ss`` or
  ``YYYY-MM-DD``), ``?s=column(asc|desc)``, ``?limit=`` (≤ 100), ``?offset=`` (≤ 10,000),
  ``?a=group,function(column)`` (aggregation; the result keys are the literal expressions, e.g.
  ``"sum(value)"``);
- ``/bitcoin/outputs``: ``transaction_hash``, ``index``, ``block_id``, ``time``, ``value``
  (satoshi), ``value_usd``, ``recipient``, ``is_from_coinbase``, ``spending_time``, ``lifespan``
  (seconds from creation to spending), groupable by ``spending_date``;
- ``/bitcoin/blocks``: ``cdd_total`` (coin days destroyed per block), groupable by ``date``;
- ``/bitcoin/outputs`` also supports counting: ``?a=date,count()`` with a ``value_usd(0..N)``
  filter counts outputs under N USD created that day — used for Phase 10's small on-chain
  transaction count (RETAIL PROXY, ``cfi.retail.universe``). **Not filtered** for change outputs
  from large transactions or exchange-internal batching — a noisy proxy, stated as such wherever
  shown, never smoothed over;
- ``/ethereum/transactions``: ``hash``, ``block_id``, ``time``, ``sender``, ``recipient``,
  ``value`` (wei, numeric string; the value filter is approximate), ``value_usd``, ``failed``;
- ``/{chain}/addresses``: ``address``, ``balance`` (satoshi integer / wei numeric string),
  default order balance descending; Bitcoin updated every 5 minutes, Ethereum daily; Ethereum
  rows carry ``is_contract``.

Terms: the free tier is for personal, non-commercial or academic use (up to 1,440 requests a day);
constant use by applications "should apply for an API key". Recorded in THIRD_PARTY_NOTICES.md.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from cfi.core.addresses import InvalidAddressError, canonical_address
from cfi.core.errors import DataValidationError, NotYetFinalError, ProviderNotConfiguredError
from cfi.domain.enums import AuthType, QualityStatus
from cfi.domain.observation import CanonicalObservation, CanonicalTransfer
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
from cfi.retail.universe import SMALL_OUTPUT_COUNT, SMALL_OUTPUT_MAX_USD
from cfi.whales.universe import (
    CHAIN_OF,
    LARGE_TRANSFER_MIN,
    LTH_MIN_AGE,
    REVIVED_MIN_AGE,
    RICH_LIST_SIZE,
    WHALE_ASSETS,
    address_ref,
    dataset,
    key_of,
    network_ref,
    transfer_ref,
)

PROVIDER_ID = "blockchair"
API_KEY_ENV = "CFI_PROVIDER_BLOCKCHAIR_API_KEY"
PAGE_LIMIT = 100
MAX_OFFSET = 10_000
SATOSHI = Decimal(100_000_000)
WEI = Decimal(10) ** 18
ATTRIBUTION = {"text": "Data: Blockchair", "url": "https://blockchair.com"}
_TIME = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HASH = re.compile(r"^(0x)?[0-9a-f]{64}$")

DAILY_METRICS = ("coin_days_destroyed", "revived_supply_1y", "lth_spent_155d", "miner_origin_spent")
# metric → (path, group column, result key, extra filter)
_AGGREGATES: dict[str, tuple[str, str, str, str]] = {
    "coin_days_destroyed": ("/bitcoin/blocks", "date", "sum(cdd_total)", ""),
    "revived_supply_1y": (
        "/bitcoin/outputs",
        "spending_date",
        "sum(value)",
        f"lifespan({int(REVIVED_MIN_AGE.total_seconds())}..)",
    ),
    "lth_spent_155d": (
        "/bitcoin/outputs",
        "spending_date",
        "sum(value)",
        f"lifespan({int(LTH_MIN_AGE.total_seconds())}..)",
    ),
    "miner_origin_spent": (
        "/bitcoin/outputs",
        "spending_date",
        "sum(value)",
        "is_from_coinbase(true)",
    ),
    # Phase 10, RETAIL PROXY: count of Bitcoin outputs under SMALL_OUTPUT_MAX_USD created that
    # day. Deliberately kept out of DAILY_METRICS (not a whale/large-holder dataset — it is not
    # registered in whales/universe.py's per-asset registry, so its dataset_id is resolved by an
    # explicit branch in first_request/parse_page below, not the dataset()/key_of() registry).
    "small_output_count": (
        "/bitcoin/outputs",
        "date",
        "count()",
        f"value_usd(0..{int(SMALL_OUTPUT_MAX_USD)})",
    ),
}
SMALL_OUTPUT_METRIC = "small_output_count"

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="Blockchair",
    base_url="https://api.blockchair.com",
    datasets=frozenset(
        [dataset(m, "BTC").dataset_id for m in DAILY_METRICS]
        + [
            dataset(m, a).dataset_id
            for m in ("address_balance", "large_transfer")
            for a in WHALE_ASSETS
        ]
        + [SMALL_OUTPUT_COUNT.dataset_id]
    ),
    auth=AuthSpec(AuthType.API_KEY_QUERY, "key", API_KEY_ENV, optional=True),
    # Documented hard limit 30 per minute without a key: one request every 3 s, no bursts.
    rate_limit=RateLimitSpec(20, 60.0, burst=1),
    max_retry_wait_seconds=60.0,
    timeout_seconds=60.0,
    max_pages=110,
    original_source="blockchair",
    terms_verified=True,
    notes=(
        "On-chain data: large Bitcoin outputs and Ethereum transactions, top-100 address "
        "balances, Bitcoin coin days destroyed and coin-age / coinbase spending aggregations. "
        "Free without a key for personal or non-commercial use up to 1,440 requests a day and "
        "30 a minute; optional key CFI_PROVIDER_BLOCKCHAIR_API_KEY."
    ),
    gap_note="Blockchair returned no value for this day",
)


def _ts(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _parse_ts(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not _TIME.fullmatch(value):
        raise DataValidationError(f"{field} is not 'YYYY-MM-DD HH:ii:ss': {value!r}")
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)


def _parse_date(value: object, field: str) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise DataValidationError(f"{field} is not 'YYYY-MM-DD': {value!r}")
    return date.fromisoformat(value)


def _optional(payload: dict[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    return None if value is None else to_decimal(value, key)


def _address(chain: str, value: object, field: str) -> tuple[str | None, list[str]]:
    """Canonical address when valid; otherwise the value as reported (flagged by the record)."""
    if value is None:
        return None, []
    if not isinstance(value, str) or not value:
        raise DataValidationError(f"{field} is not a string: {value!r}")
    try:
        canonical = canonical_address(chain, value)
    except InvalidAddressError:
        return value, []
    return canonical, ([f"{field}: canonical form (lower case)"] if canonical != value else [])


class Blockchair(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    # ------------------------------------------------------------------ requests

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        if dataset_id == SMALL_OUTPUT_COUNT.dataset_id:
            if window.subject != "BTC":
                raise ProviderNotConfiguredError(
                    f"Blockchair: {dataset_id!r} is not configured for {window.subject!r}.",
                    provider_id=PROVIDER_ID,
                )
            last = window.end - timedelta(seconds=1)
            _, group, key, extra = _AGGREGATES[SMALL_OUTPUT_METRIC]
            q = f"time({window.start.date().isoformat()}..{last.date().isoformat()}),{extra}"
            return RequestSpec(
                "/bitcoin/outputs",
                params={"a": f"{group},{key}", "q": q},
                state={"metric": SMALL_OUTPUT_METRIC, "asset": "BTC", "chain": "bitcoin"},
            )
        try:
            metric, asset = key_of(dataset_id)
        except KeyError:
            metric, asset = "", ""
        if dataset_id not in CAPABILITIES.datasets or window.subject != asset:
            raise ProviderNotConfiguredError(
                f"Blockchair: {dataset_id!r} is not configured for {window.subject!r}.",
                provider_id=PROVIDER_ID,
            )
        chain = CHAIN_OF[asset]
        last = window.end - timedelta(seconds=1)  # ranges are inclusive; the window is not
        state = {"metric": metric, "asset": asset, "chain": chain}
        if metric == "address_balance":
            params = {"s": "balance(desc)", "limit": str(RICH_LIST_SIZE)}
            if chain == "ethereum":
                params["q"] = "is_contract(false)"
            return RequestSpec(f"/{chain}/addresses", params=params, state=state)
        if metric == "large_transfer":
            minimum = LARGE_TRANSFER_MIN[asset]
            if chain == "bitcoin":
                q = f"value({int(minimum * SATOSHI)}..),time({_ts(window.start)}..{_ts(last)})"
                path = "/bitcoin/outputs"
            else:
                q = (
                    f"value({int(minimum * WEI)}..),time({_ts(window.start)}..{_ts(last)}),"
                    "failed(false)"
                )
                path = "/ethereum/transactions"
            return RequestSpec(
                path,
                params={"q": q, "s": "time(asc)", "limit": str(PAGE_LIMIT), "offset": "0"},
                state=state,
            )
        path, group, key, extra = _AGGREGATES[metric]
        column = "time" if group == "date" else "spending_time"
        start_day, last_day = window.start.date(), last.date()
        q = f"{column}({start_day.isoformat()}..{last_day.isoformat()})"
        if extra:
            q += f",{extra}"
        return RequestSpec(path, params={"a": f"{group},{key}", "q": q}, state=state)

    def next_request(
        self, previous: RequestSpec, raw: RawResponse, records: Sequence[ProviderRecord]
    ) -> RequestSpec | None:
        if previous.state.get("metric") != "large_transfer":
            return None
        context = self._context(raw)
        offset = int(previous.params.get("offset", "0")) + PAGE_LIMIT
        total = context.get("total_rows")
        rows = context.get("rows")
        if not isinstance(total, int) or not isinstance(rows, int):
            raise schema_error(raw, "context.total_rows / context.rows are not integers")
        if rows < PAGE_LIMIT or offset >= total:
            return None
        if offset > MAX_OFFSET:
            raise schema_error(
                raw, f"more than {MAX_OFFSET} matching rows: the window must be split"
            )
        return RequestSpec(
            previous.path,
            params={**previous.params, "offset": str(offset)},
            page=previous.page + 1,
            state=previous.state,
        )

    # ------------------------------------------------------------------ parsing

    @staticmethod
    def _body(raw: RawResponse) -> dict[str, Any]:
        body = load_json(raw)
        if not isinstance(body, dict) or "context" not in body or "data" not in body:
            raise schema_error(raw, "expected an object with 'data' and 'context'")
        return body

    def _context(self, raw: RawResponse) -> dict[str, Any]:
        context = self._body(raw)["context"]
        if not isinstance(context, dict):
            raise schema_error(raw, "'context' is not an object")
        return context

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        raise NotImplementedError("Blockchair pages are parsed with their request (parse_page)")

    def parse_page(self, spec: RequestSpec, raw: RawResponse) -> Sequence[ProviderRecord]:
        body = self._body(raw)
        context = self._context(raw)
        if context.get("code") != 200:
            raise schema_error(raw, f"context.code is {context.get('code')!r}, not 200")
        data = body["data"]
        if data is None:
            data = []
        if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
            raise schema_error(raw, "'data' is not a list of objects")
        metric, asset = spec.state["metric"], spec.state["asset"]
        dataset_id = (
            SMALL_OUTPUT_COUNT.dataset_id
            if metric == SMALL_OUTPUT_METRIC
            else dataset(metric, asset).dataset_id
        )
        required = {
            "address_balance": ("address", "balance"),
            "large_transfer": (
                ("transaction_hash", "index", "time", "value", "recipient")
                if asset == "BTC"
                else ("hash", "time", "value", "sender", "recipient")
            ),
        }.get(metric)
        if required is None:
            _, group, key, _ = _AGGREGATES[metric]
            required = (group, key)
        records = []
        for rank, row in enumerate(data, start=int(spec.params.get("offset", "0")) + 1):
            missing = [k for k in required if k not in row]
            if missing:
                raise schema_error(raw, f"row lacks {', '.join(missing)}")
            payload = {**row, "_metric": metric, "_asset": asset, "_rank": rank}
            if metric not in ("address_balance", "large_transfer"):
                payload["_day"] = row[required[0]]
                payload["_value"] = row[required[1]]
            records.append(ProviderRecord(PROVIDER_ID, dataset_id, payload))
        return records

    # ------------------------------------------------------------------ normalisation

    def normalise(
        self, record: ProviderRecord, ctx: NormaliseContext
    ) -> CanonicalObservation | CanonicalTransfer:
        p = dict(record.payload)
        metric = p["_metric"]
        if metric == "large_transfer":
            return self._transfer(p, ctx)
        if metric == "address_balance":
            return self._balance(p, ctx)
        return self._daily(p, ctx)

    def _common(self, ctx: NormaliseContext) -> dict[str, Any]:
        spec = ctx.dataset
        return {
            "dataset_id": spec.dataset_id,
            "metric": spec.metric,
            "period": spec.period,
            "unit": spec.unit,
            "venue": None,
            "ingested_at": ctx.ingested_at,
            "source_provider": PROVIDER_ID,
            "original_source": CAPABILITIES.original_source,
            "raw_ref": ctx.raw_ref,
        }

    def _daily(self, p: dict[str, Any], ctx: NormaliseContext) -> CanonicalObservation:
        spec = ctx.dataset
        day = _parse_date(p["_day"], "date")
        event_time = datetime(day.year, day.month, day.day, tzinfo=UTC)
        available_at, estimated = spec.available_at(event_time, None, ctx.ingested_at)
        raw_value = p["_value"]
        transformations = [f"event_time: date {day.isoformat()} -> 00:00 UTC label"]
        if raw_value is None:
            value = None
        elif spec.unit == "btc":
            value = to_decimal(raw_value, "sum(value)") / SATOSHI
            transformations.append("value: satoshi / 100,000,000 -> BTC")
        else:
            value = to_decimal(raw_value, "sum(cdd_total)")
        return CanonicalObservation(
            **self._common(ctx),
            asset="BTC",
            subject_ref=network_ref("BTC"),
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            value=value,
            quality_status=QualityStatus.MISSING if value is None else QualityStatus.OK,
            quality_note="aggregation returned no value" if value is None else None,
            pit_reliability=spec.pit_reliability(available_at, ctx.ingested_at),
            transformations=tuple(transformations),
        )

    def _balance(self, p: dict[str, Any], ctx: NormaliseContext) -> CanonicalObservation:
        spec = ctx.dataset
        asset = p["_asset"]
        chain = CHAIN_OF[asset]
        try:
            address = canonical_address(chain, str(p["address"]))
        except InvalidAddressError as exc:
            raise DataValidationError(f"address {p['address']!r}: {exc}") from exc
        balance = to_decimal(p["balance"], "balance")
        scale, unit_name = (SATOSHI, "satoshi") if chain == "bitcoin" else (WEI, "wei")
        transformations = [
            f"value: {unit_name} -> {spec.unit.upper()}",
            f"rank {p['_rank']} of {RICH_LIST_SIZE} by balance at the snapshot",
        ]
        if address != p["address"]:
            transformations.append("address: canonical form (lower case)")
        # The list has no timestamp: the snapshot is dated by its receipt (``provider`` rule).
        event_time = ctx.ingested_at
        available_at, estimated = spec.available_at(event_time, None, ctx.ingested_at)
        return CanonicalObservation(
            **self._common(ctx),
            asset=asset,
            subject_ref=address_ref(chain, address),
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            value=balance / scale,
            quality_status=QualityStatus.OK,
            pit_reliability=spec.pit_reliability(available_at, ctx.ingested_at),
            transformations=tuple(transformations),
        )

    def _transfer(self, p: dict[str, Any], ctx: NormaliseContext) -> CanonicalTransfer:
        spec = ctx.dataset
        asset = p["_asset"]
        chain = CHAIN_OF[asset]
        event_time = _parse_ts(p["time"], "time")
        if event_time > ctx.ingested_at:
            raise NotYetFinalError("block time is after the time of receipt")
        available_at, estimated = spec.available_at(event_time, None, ctx.ingested_at)
        transformations = ["event_time: block time 'YYYY-MM-DD HH:ii:ss' (UTC) -> UTC"]
        if chain == "bitcoin":
            tx_hash = p["transaction_hash"]
            index = p["index"]
            if not isinstance(index, int) or isinstance(index, bool) or index < 0:
                raise DataValidationError(f"output index is not a non-negative integer: {index!r}")
            value = to_decimal(p["value"], "value") / SATOSHI
            transformations.append("value_native: satoshi / 100,000,000 -> BTC")
            sender: str | None = None
            sender_notes: list[str] = []
        else:
            tx_hash = p["hash"]
            index = None
            value = to_decimal(p["value"], "value") / WEI
            transformations.append("value_native: wei / 10^18 -> ETH")
            sender, sender_notes = _address(chain, p["sender"], "sender")
        if not isinstance(tx_hash, str) or not _HASH.fullmatch(tx_hash):
            raise DataValidationError(f"transaction hash is malformed: {tx_hash!r}")
        recipient, recipient_notes = _address(chain, p["recipient"], "recipient")
        block = p.get("block_id")
        if block is not None and (not isinstance(block, int) or isinstance(block, bool)):
            raise DataValidationError(f"block_id is not an integer: {block!r}")
        return CanonicalTransfer(
            **self._common(ctx),
            asset=asset,
            subject_ref=transfer_ref(chain, tx_hash, index),
            event_time=event_time,
            available_at=available_at,
            available_at_estimated=estimated,
            chain=chain,
            tx_hash=tx_hash,
            output_index=index,
            block_height=block,
            sender=sender,
            recipient=recipient,
            value_native=value,
            value_usd=_optional(p, "value_usd"),
            quality_status=QualityStatus.OK,
            pit_reliability=spec.pit_reliability(available_at, ctx.ingested_at),
            transformations=tuple(transformations + sender_notes + recipient_notes),
        )
