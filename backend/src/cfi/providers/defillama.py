"""DefiLlama stablecoins public data — circulating supply, no key (Phase 9).

Endpoints (base ``https://stablecoins.llama.fi``, confirmed live 2026-09-26 via a real fetched
response, and against DefiLlama's published API docs, https://api-docs.defillama.com/):

- ``GET /stablecoins?includePrices=true`` → ``{"peggedAssets": [{"id", "name", "symbol",
  "circulating": {"peggedUSD": <number>}, "chainCirculating": {...}, ...}], "chains": [...],
  "price": ...}``. Used only to confirm the id ↔ symbol mapping (``1`` = Tether/USDT, ``2`` = USD
  Coin/USDC); not used for the stored series.
- ``GET /stablecoincharts/all`` → array of ``{"date": "<unix seconds, digit string>",
  "totalCirculating": {"peggedUSD": <number>}, "totalCirculatingUSD": {...},
  "totalUnreleased": {...}}``, ascending by date, one row per calendar day, covering every
  stablecoin DefiLlama tracks (used for the TOTAL subject).
- ``GET /stablecoincharts/all?stablecoin={id}`` → the same shape, scoped to one stablecoin (used
  for USDT ``id=1`` and USDC ``id=2``).

**Important provider quirk, handled here rather than assumed away:** these chart endpoints take
no date-range parameters — every call returns the **entire** history from DefiLlama's first
tracked day (November 2017) to the most recent one, however far back or how "recent" the caller
actually wants. There is no pagination to drive with ``next_request``; the full array always
comes back in one response. The adapter therefore fetches the whole array on every call and
filters it, in ``parse_page``, down to the rows that actually fall inside the requested
``FetchWindow`` — everything else is discarded there rather than stored. This means requests are
naturally larger than most other adapters' (a growing multi-year array, not a bounded page), which
is why this source is scheduled at a low frequency (Phase 9 ``sources.py``): the data itself only
changes once a day, so polling more often than that buys nothing.

**Not verified against a raw byte-exact response captured in this workspace.** DefiLlama's host is
not reachable from Claude's development sandbox (egress proxy denies it, like Blockchair in Phase
7); the field names and shapes above were confirmed through a live fetch made through a different
tool with web access, not captured as bytes here. Real verification — and updating the test
fixtures with an actual captured payload — happens once the user's machine performs a real
ingestion run (Phase 9 ``TODO.md``), the same process used for Binance in Phase 8.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from cfi.domain.enums import QualityStatus
from cfi.domain.observation import CanonicalObservation
from cfi.liquidity.records import epoch_seconds, scalar
from cfi.liquidity.universe import STABLECOINS, SUPPLY, TOTAL_SUBJECT, supply_ref
from cfi.providers.base import (
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

PROVIDER_ID = "defillama"
CHARTS_PATH = "/stablecoincharts/all"
IDS: dict[str, str] = STABLECOINS  # {"USDT": "1", "USDC": "2"}
ATTRIBUTION = {"text": "Source: DefiLlama stablecoins", "url": "https://defillama.com/stablecoins"}

CAPABILITIES = ProviderCapabilities(
    provider_id=PROVIDER_ID,
    display_name="DefiLlama stablecoins",
    base_url="https://stablecoins.llama.fi",
    datasets=frozenset({SUPPLY.dataset_id}),
    # No documented rate limit found; paced conservatively (one request every 2 seconds) since
    # every call returns the full multi-year history, not a small page.
    rate_limit=RateLimitSpec(1, 2.0, burst=1),
    timeout_seconds=20.0,
    max_pages=1,
    original_source="defillama",
    terms_verified=False,
    notes=(
        "USDT, USDC and total (every tracked stablecoin) circulating supply, daily, aggregated "
        "across all chains, back to November 2017. No key. Field shapes confirmed via a live "
        "fetch through a tool with web access, not a raw response captured in this workspace "
        "(DefiLlama's host is not reachable from it) — see this module's docstring. Terms of use "
        "not yet reviewed by the user."
    ),
    gap_note="DefiLlama published no circulating-supply row for this day",
)


def _data(raw: RawResponse) -> list[object]:
    body = load_json(raw)
    if not isinstance(body, list):
        raise schema_error(raw, "expected a JSON array of daily circulating-supply rows")
    return body


class DefiLlama(ProviderAdapter):
    @property
    def capabilities(self) -> ProviderCapabilities:
        return CAPABILITIES

    def first_request(self, dataset_id: str, window: FetchWindow) -> RequestSpec:
        subject = window.subject
        if subject is None or subject not in (*IDS, TOTAL_SUBJECT):
            raise ValueError(f"DefiLlama: no stablecoin subject for window {window!r}")
        params = {} if subject == TOTAL_SUBJECT else {"stablecoin": IDS[subject]}
        state = {
            "subject": subject,
            "dataset_id": dataset_id,
            "start_s": str(int(window.start.timestamp())),
            "end_s": str(int(window.end.timestamp())),
        }
        return RequestSpec(CHARTS_PATH, params, state=state)

    # No pagination: every response already contains the entire history (see module docstring).
    # next_request defaults to None (ProviderAdapter's base implementation).

    def parse(self, raw: RawResponse) -> Sequence[ProviderRecord]:
        raise NotImplementedError("DefiLlama rows are parsed with their request (parse_page)")

    def parse_page(self, spec: RequestSpec, raw: RawResponse) -> Sequence[ProviderRecord]:
        subject, dataset_id = spec.state["subject"], spec.state["dataset_id"]
        start_s, end_s = int(spec.state["start_s"]), int(spec.state["end_s"])
        rows = _data(raw)
        out: list[ProviderRecord] = []
        for row in rows:
            if not isinstance(row, dict) or "date" not in row or "totalCirculating" not in row:
                raise schema_error(raw, "row must have 'date' and 'totalCirculating'")
            date_s = row["date"]
            if not (isinstance(date_s, str) and date_s.isdigit()):
                raise schema_error(raw, f"'date' must be a digit string, got {date_s!r}")
            ts = int(date_s)
            if not (start_s <= ts < end_s):
                continue  # outside the requested window — see module docstring
            circulating = row["totalCirculating"]
            if not isinstance(circulating, dict) or "peggedUSD" not in circulating:
                raise schema_error(raw, "'totalCirculating' must have a 'peggedUSD' field")
            payload = {
                "subject": subject,
                "date": date_s,
                "value": circulating["peggedUSD"],
            }
            out.append(ProviderRecord(PROVIDER_ID, dataset_id, payload))
        return out

    def normalise(self, record: ProviderRecord, ctx: NormaliseContext) -> CanonicalObservation:
        p = record.payload
        subject = str(p["subject"])
        event_time: datetime = epoch_seconds(p["date"], "date")
        value = to_decimal(p["value"], "peggedUSD")
        quality, note = QualityStatus.OK, None
        if value < 0:
            quality, note = QualityStatus.SUSPECT, f"negative circulating supply reported: {value}"
        return scalar(
            ctx,
            provider_id=PROVIDER_ID,
            original_source=CAPABILITIES.original_source,
            asset=subject,
            subject_ref=supply_ref(subject),
            event_time=event_time,
            value=value,
            transformations=("value: DefiLlama peggedUSD, aggregated across all chains",),
            quality=quality,
            note=note,
        )
