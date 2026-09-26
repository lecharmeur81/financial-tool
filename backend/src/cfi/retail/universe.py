"""Retail activity intelligence datasets (Phase 10).

**Every input below is labelled DIRECT RETAIL DATA or RETAIL PROXY — never presented as the
other.** No source found publishes data identified by its provider as "retail" specifically
(no exchange or vendor checked segments its public data by account type); every input tracked
here is therefore a **RETAIL PROXY**: a signal *believed* to skew retail, for a stated reason,
never itself proof of retail origin (R1, R5's "large ≠ institutional" applies symmetrically:
skewed-toward-numerous ≠ retail).

**Tracked (RETAIL PROXY, all)**

- **Retail derivatives positioning** — reuses two datasets Phase 8 already ingests from Binance
  USDⓈ-M Futures (``cfi.providers.binance_futures``), read here, not re-ingested:
  ``deriv.funding_rate`` and ``deriv.long_short_account_ratio.1h`` (BTC, ETH, SOL, XRP). Binance's
  "global" account-ratio counts *accounts*, not position size, and retail traders vastly
  outnumber large accounts — so an account-count ratio skews toward the numerous small accounts
  even though a single large account counts equally. Funding rate reflects perpetual-swap demand
  broadly (leveraged longs paying shorts, or the reverse), a widely used proxy for crowded
  leveraged speculation, not filtered to retail. Neither field is retail-exclusive; both are
  proxies, stated as such everywhere they are shown.
- **Meme-coin / retail search-attention proxy** — CoinGecko's ``/search/trending`` endpoint (free,
  keyless, documented at docs.coingecko.com/reference/trending-search; confirmed live
  2026-09-26), which ranks the top ~15 coins by recent search interest on coingecko.com. This
  reflects retail-style browsing/search behaviour (a professional desk does not shop for coins
  on a public search box) but is still a proxy: it measures search interest on one website, not
  trades, wallets, or account types. Every trending coin returned is stored; a curated,
  explicitly non-exhaustive list of well-known meme coins (``MEME_COIN_SYMBOLS``) is used to
  compute the meme-coin-specific reading from the same stored data.
- **Small on-chain transaction activity** — Blockchair Bitcoin aggregation (already used for
  whale intelligence, Phase 7, ``cfi.providers.blockchair``): count of Bitcoin outputs valued
  under ``SMALL_OUTPUT_MAX_USD`` per UTC day. A count of small-value transfers is a common retail
  proxy, but is **not** filtered for change outputs (a large transaction can create a small
  change output), exchange-internal batching, or dust — stated plainly wherever this metric is
  shown, never smoothed over.

**Not tracked, and said so** (``NOT_TRACKED``):

- **Google Trends** — no official public API for search-interest data exists (the documented,
  supported route is the Google Trends BigQuery public dataset, which needs a paid Google Cloud
  billing account, not a $0-budget key). The commonly used unofficial route (scraping
  ``trends.google.com``'s internal endpoints, e.g. via the ``pytrends`` library) is not
  authorised by Google's terms of service for automated, sustained use; this platform does not
  build on an unauthorised scrape (R9-adjacent judgment call, same posture as the copyright/ToS
  caution elsewhere in this project).
- **Reddit activity** — Reddit's API moved to paid, metered pricing in 2023 (confirmed still in
  effect 2026); the free allowance is scoped to small-scale, non-commercial use. Using it for a
  commercial capital-flow platform at any meaningful volume is a paid-licensing and terms-of-use
  decision for the user to make, not one this build makes silently. Not integrated pending that
  decision.
- **Social activity (Twitter/X and similar)** — X's API has no free tier that supports search or
  aggregate content retrieval (the free tier is essentially post-only for one's own account);
  meaningful read access is a paid tier. Same posture as Reddit: a licensing decision for the
  user, not integrated here.

Every one of the three NOT_TRACKED items above is a **business/licensing decision**, not a
technical dead end — restated in ``TODO.md`` for the user's review.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from cfi.domain.datasets import AvailabilityRule, DatasetSpec

# A deliberately small, well-known, non-exhaustive set used only to compute the meme-coin-specific
# reading from the generic trending feed (every trending coin is stored regardless of this list).
MEME_COIN_SYMBOLS: tuple[str, ...] = ("DOGE", "SHIB", "PEPE", "WIF", "BONK", "FLOKI")

# Sentinel "subject" for the trending scheduled source: one call returns every trending coin (a
# dynamic, not-known-in-advance set of assets), so there is no single fixed subject to key
# staleness/backfill checks on (see retail/sources.py for how this is handled).
TRENDING_SUBJECT = "GLOBAL"

# Judgment parameter (not fitted to data): an output below this value counts toward the small
# on-chain transaction count. USD (Blockchair's own value_usd field, integer boundary).
SMALL_OUTPUT_MAX_USD = Decimal(1000)

NOT_TRACKED: tuple[dict[str, str], ...] = (
    {
        "item": "Google Trends search interest",
        "reason": "No official public API (the supported route needs a paid Google Cloud "
        "BigQuery account); the unofficial scraping route used by most third-party libraries "
        "is not authorised by Google's terms of service for sustained automated use.",
    },
    {
        "item": "Reddit activity (post/comment volume, sentiment)",
        "reason": "Reddit's API is metered/paid beyond a small non-commercial free allowance "
        "(since 2023, still in effect). Using it commercially at meaningful volume is a "
        "paid-licensing decision for the user, not made silently by this build.",
    },
    {
        "item": "Social activity (Twitter/X and similar platforms)",
        "reason": "No free tier supports search or aggregate content retrieval on X; meaningful "
        "read access requires a paid API tier. Same posture as Reddit — a licensing decision "
        "for the user.",
    },
)

# CoinGecko's trending endpoint carries no timestamp; each poll is a live snapshot known the
# moment it is received (mirrors the treasury-holdings dataset already ingested from the same
# provider, Phase 6 — see providers/coingecko.py's TREASURY_HOLDINGS_COMPANIES).
_LIVE_SNAPSHOT = AvailabilityRule("provider")

TRENDING = DatasetSpec(
    dataset_id="retail.trending_coin_rank",
    metric="trending_rank",
    unit="rank",
    period="event",
    availability=_LIVE_SNAPSHOT,
    freshness_limit=timedelta(hours=8),
    conflict_tolerance=Decimal("0"),
    revisable=False,
    kind="scalar",
    description=(
        "One coin's position in CoinGecko's top trending-by-search-interest list at the time "
        "of the poll (0 = most trending of that poll's top ~15; a coin absent from the list "
        "that poll has no observation, not a zero). event_time = the time the snapshot was "
        "received (the endpoint carries no timestamp of its own)."
    ),
)

# Blockchair aggregates over complete UTC days; asked for two hours after the day closes (mirrors
# whales/universe.py's _DAY_CLOSED rule for the same provider's other daily aggregations).
_DAY_CLOSED = AvailabilityRule("period_end_plus", timedelta(hours=2))

SMALL_OUTPUT_COUNT = DatasetSpec(
    dataset_id="retail.small_output_count.btc.1d",
    metric="small_output_count",
    unit="count",
    period="1d",
    availability=_DAY_CLOSED,
    freshness_limit=timedelta(days=3),
    conflict_tolerance=Decimal("0.01"),
    revisable=True,
    kind="scalar",
    description=(
        f"Count of Bitcoin transaction outputs valued under ${SMALL_OUTPUT_MAX_USD} (Blockchair's "
        "value_usd field) created during the UTC day. Not filtered for change outputs from large "
        "transactions, exchange-internal batching, or dust — a noisy proxy, stated as such."
    ),
)


def coin_ref(coin_id: str) -> str:
    """CoinGecko's own coin slug, e.g. 'dogecoin' — used because the trending set of assets is
    not known in advance (unlike every other provider in this project, which requests a fixed,
    pre-registered list of coin ids)."""
    return f"COINGECKO:{coin_id}"


def all_datasets() -> list[DatasetSpec]:
    return [TRENDING, SMALL_OUTPUT_COUNT]


def dataset_by_id(dataset_id: str) -> DatasetSpec:
    for spec in all_datasets():
        if spec.dataset_id == dataset_id:
            return spec
    raise KeyError(dataset_id)
