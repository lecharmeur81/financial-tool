"""Liquidity / stablecoin datasets (Phase 9).

What is tracked and where it comes from (public, no key): **DefiLlama's stablecoins API**
(`stablecoins.llama.fi`) publishes one circulating-supply snapshot per calendar day, aggregated
across every chain a stablecoin is issued on, for USDT, USDC and every other stablecoin it tracks.
We store three daily series from it:

- **USDT** circulating supply (Tether, DefiLlama id ``1``);
- **USDC** circulating supply (Circle USD Coin, DefiLlama id ``2``);
- **total** circulating supply of every stablecoin DefiLlama tracks (sum across issuers).

USDT and USDC market share is a calculated metric (Phase 9 ``metrics.py``): each issuer's supply
÷ the total, both from these same stored series — never fetched pre-computed from a vendor.

"Minting" and "burning" are not captured as individual on-chain events here (that would need
per-chain contract-event tracking on Ethereum, Tron and every other issuing chain — a much larger
scope). Instead, day-over-day changes in stored circulating supply serve as the observable proxy:
a positive change is net minting exceeding burning that day, a negative change the reverse. This
is stated plainly wherever it is shown (never presented as an exact minting/burning transaction
count).

**Not available from any free source found** (``NOT_TRACKED``): stablecoin balances held on
exchange addresses, and stablecoin flows into or out of exchanges. This would need labelled
on-chain address attribution for ERC-20 / TRC-20 / other token transfers to known exchange
wallets — the free tier of every provider checked (DefiLlama, Coin Metrics, Blockchair) publishes
aggregate circulating supply, not per-holder or per-exchange balances. Paid providers (Nansen,
Arkham, CryptoQuant) offer this; out of scope for a $0 budget. The "exchange liquidity changes"
calculation this phase was asked for is defined in ``metrics.py`` but always returns
"unavailable" for exactly this reason — a named, visible gap rather than a silently skipped one.

``event_time`` convention: DefiLlama's ``date`` field is the calendar day (UTC midnight) the
snapshot describes. Exactly when during (or after) that day DefiLlama's crawl actually captures
and publishes it is not documented; treated conservatively as knowable by the end of that UTC day
plus a margin, falling back to receipt time when a row is seen earlier than that estimate (the
same conservative pattern already used for Deribit snapshots in Phase 8, ``known_when_received``).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from cfi.domain.datasets import AvailabilityRule, DatasetSpec

# DefiLlama's internal ids for the two issuers we track individually (confirmed live 2026-09-26:
# id "1" -> Tether/USDT, id "2" -> USD Coin/USDC; see providers/defillama.py).
STABLECOINS: dict[str, str] = {"USDT": "1", "USDC": "2"}
TOTAL_SUBJECT = "TOTAL"
SUBJECTS: tuple[str, ...] = (*STABLECOINS, TOTAL_SUBJECT)
DAY = timedelta(days=1)

NOT_TRACKED: tuple[dict[str, str], ...] = (
    {
        "item": "Exchange stablecoin balances",
        "reason": "No free source found publishes per-exchange stablecoin holdings; would need "
        "labelled on-chain address attribution (paid: Nansen, Arkham, CryptoQuant).",
    },
    {
        "item": "Stablecoin exchange flows",
        "reason": "Same as exchange balances: needs labelled address-level transfer tracking, "
        "not published free anywhere found. The 'exchange liquidity change' calculation is "
        "defined but always reports unavailable, rather than being silently omitted.",
    },
    {
        "item": "Individual mint / burn transactions",
        "reason": "Day-over-day change in stored circulating supply is used as the observable "
        "proxy for net minting/burning; per-transaction issuer treasury events (e.g. exact "
        "Tether Treasury contract mints) are not ingested — that needs per-chain contract-event "
        "tracking on every issuing chain.",
    },
    {
        "item": "Stablecoins beyond USDT and USDC tracked individually",
        "reason": "DAI, USDe, USDS and others are counted only inside 'total stablecoin supply' "
        "(DefiLlama tracks them too), not broken out as their own named series.",
    },
)

# DefiLlama's crawl timing for a given day is not documented; treated as knowable by the end of
# that UTC day (event_time + 24 h) plus a half-day margin, falling back to receipt time if seen
# earlier (as Phase 8 does for Deribit snapshots whose exact publish moment is likewise not
# documented). "event_time_plus" (not "period_end_plus") is what makes that fallback valid — see
# ``domain/datasets.py``: ``known_when_received`` is only for an *estimated* availability rule.
_DAILY_SNAPSHOT = AvailabilityRule("event_time_plus", timedelta(hours=36), known_when_received=True)

SUPPLY = DatasetSpec(
    dataset_id="liquidity.stablecoin_supply.1d",
    metric="stablecoin_supply",
    unit="usd",
    period="1d",
    availability=_DAILY_SNAPSHOT,
    freshness_limit=timedelta(hours=36),
    conflict_tolerance=Decimal("0.001"),
    revisable=True,
    expect_continuous=True,
    description=(
        "Circulating supply of a stablecoin (or, for subject TOTAL, every stablecoin DefiLlama "
        "tracks) in USD, aggregated across every chain, one value per calendar day "
        "(event_time = UTC midnight of the day described)."
    ),
)


def supply_ref(subject: str) -> str:
    """The canonical subject_ref for a tracked stablecoin or the total."""
    return f"STABLECOIN:{subject}"


def all_datasets() -> list[DatasetSpec]:
    return [SUPPLY]


def dataset_by_id(dataset_id: str) -> DatasetSpec:
    if dataset_id == SUPPLY.dataset_id:
        return SUPPLY
    raise KeyError(dataset_id)
