"""Whale intelligence datasets (Phase 7).

What is tracked, where it comes from, and how directly it identifies *who* is acting (R5):

- exchange inflow / outflow / exchange supply (BTC, ETH, daily) — Coin Metrics Community;
  actor evidence **attributed** (Coin Metrics' exchange address attribution);
- network supply and new issuance (BTC, ETH, daily) — Coin Metrics; not actor data;
- coin days destroyed, revived ≥ 1 y supply, ≥ 155 d supply spent, spending of newly mined
  (coinbase) coins (BTC, daily) — Blockchair aggregations; coin age and origin, not owners;
- top-100 address balances (BTC; ETH accounts, contracts excluded) — Blockchair; an address, not
  an owner (labels come from ``ref.entity_label``);
- large transfers (BTC outputs ≥ 500 BTC; ETH transactions ≥ 5,000 ETH) — Blockchair; addresses,
  not owners.

A large balance or transfer is never evidence of an institution (R5: large ≠ institutional). An
address without a label is "unknown"; with a large balance it is an *unknown large holder*.

Not available from free sources (recorded in ``NOT_TRACKED``): the stock of dormant or long-term
holder supply, flows between miners and exchanges, whale data for SOL and XRP, labelled Ethereum
addresses.

``event_time`` conventions: daily datasets use the UTC day (00:00 label, the day it covers);
transfers use the block time; balances use the time the snapshot was received.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Literal

from cfi.core.addresses import Chain
from cfi.domain.datasets import AvailabilityRule, DatasetSpec, RecordKind

WHALE_ASSETS: tuple[str, ...] = ("BTC", "ETH")
DORMANCY_ASSETS: tuple[str, ...] = ("BTC",)  # coin-age and coinbase data: Bitcoin only
CHAIN_OF: dict[str, Chain] = {"BTC": "bitcoin", "ETH": "ethereum"}
ASSET_OF: dict[str, str] = {chain: asset for asset, chain in CHAIN_OF.items()}

# Judgment parameters (not fitted to data), shown with every result that uses them.
LARGE_TRANSFER_MIN: dict[str, Decimal] = {"BTC": Decimal(500), "ETH": Decimal(5_000)}
# An unlabelled address holding at least this much is an "unknown large holder" (inferred, size
# only). Every address in the top-100 lists is far above these amounts.
LARGE_HOLDER_MIN: dict[str, Decimal] = {"BTC": Decimal(1_000), "ETH": Decimal(10_000)}
RICH_LIST_SIZE = 100
REVIVED_MIN_AGE = timedelta(days=365)
LTH_MIN_AGE = timedelta(days=155)

Family = Literal["exchange", "network", "dormancy", "miner", "balance", "transfer"]

# Coin Metrics publishes day D at about 02:00 UTC on D+1 with a status time; values without one
# (network supply, issuance) are estimated as knowable 30 h after the day starts.
_PROVIDER_TIME = AvailabilityRule("provider")
_NETWORK_DAY = AvailabilityRule("event_time_plus", timedelta(hours=30), known_when_received=True)
# Blockchair aggregates over complete UTC days; asked for from two hours after the day closes.
_DAY_CLOSED = AvailabilityRule("period_end_plus", timedelta(hours=2))
# Blocks are indexed by Blockchair within minutes; later receipt is dated by receipt.
_BLOCK = AvailabilityRule("event_time_plus", timedelta(minutes=10), known_when_received=True)


def exchange_ref(asset: str) -> str:
    """Coin Metrics' set of attributed exchange addresses for one asset."""
    return f"EXCHANGES:{asset}"


def network_ref(asset: str) -> str:
    return f"NETWORK:{asset}"


def address_ref(chain: str, address: str) -> str:
    return f"{chain}:{address}"


def transfer_ref(chain: str, tx_hash: str, output_index: int | None) -> str:
    return f"{chain}:{tx_hash}" + ("" if output_index is None else f":{output_index}")


def _daily(
    dataset_id: str,
    metric: str,
    unit: str,
    availability: AvailabilityRule,
    description: str,
) -> DatasetSpec:
    return DatasetSpec(
        dataset_id=dataset_id,
        metric=metric,
        unit=unit,
        period="1d",
        availability=availability,
        freshness_limit=timedelta(days=3),
        conflict_tolerance=Decimal("0.01"),
        revisable=True,
        description=description,
    )


def _per_asset() -> dict[tuple[str, str], DatasetSpec]:
    out: dict[tuple[str, str], DatasetSpec] = {}
    for asset in WHALE_ASSETS:
        a = asset.lower()
        out[("exchange_inflow", asset)] = _daily(
            f"whale.exchange_inflow.{a}.1d",
            "exchange_inflow",
            a,
            _PROVIDER_TIME,
            f"{asset} received by exchange addresses during the UTC day (native units), as "
            "attributed by Coin Metrics.",
        )
        out[("exchange_outflow", asset)] = _daily(
            f"whale.exchange_outflow.{a}.1d",
            "exchange_outflow",
            a,
            _PROVIDER_TIME,
            f"{asset} sent from exchange addresses during the UTC day (native units), as "
            "attributed by Coin Metrics.",
        )
        out[("exchange_supply", asset)] = _daily(
            f"whale.exchange_supply.{a}.1d",
            "exchange_supply",
            a,
            _PROVIDER_TIME,
            f"{asset} held by exchange addresses at the end of the UTC day (native units), as "
            "attributed by Coin Metrics.",
        )
        out[("supply", asset)] = _daily(
            f"whale.supply.{a}.1d",
            "supply",
            a,
            _NETWORK_DAY,
            f"Current {asset} supply at the end of the UTC day (native units, Coin Metrics).",
        )
        out[("issuance", asset)] = _daily(
            f"whale.issuance.{a}.1d",
            "issuance",
            a,
            _NETWORK_DAY,
            f"New {asset} issued during the UTC day (native units, Coin Metrics).",
        )
        chain = CHAIN_OF[asset]
        out[("address_balance", asset)] = DatasetSpec(
            dataset_id=f"whale.address_balance.{chain}",
            metric="address_balance",
            unit=a,
            period="event",
            availability=AvailabilityRule("provider"),
            freshness_limit=timedelta(hours=36),
            conflict_tolerance=Decimal("0.001"),
            revisable=True,
            description=(
                f"Balance of each of the {RICH_LIST_SIZE} largest {chain} "
                + ("addresses" if asset == "BTC" else "accounts (contracts excluded)")
                + " (native units), snapshot as listed by Blockchair. event_time = time the "
                "snapshot was received (the list carries no timestamp)."
            ),
        )
        kind: RecordKind = "transfer"
        out[("large_transfer", asset)] = DatasetSpec(
            dataset_id=f"whale.large_transfer.{chain}",
            metric="large_transfer",
            unit=a,
            period="event",
            availability=_BLOCK,
            freshness_limit=timedelta(days=1),
            conflict_tolerance=Decimal(0),
            revisable=True,
            kind=kind,
            check_freshness=False,
            description=(
                "Bitcoin transaction outputs of at least "
                f"{LARGE_TRANSFER_MIN['BTC']:,} BTC (recipient address; senders are not part of "
                "an output)"
                if asset == "BTC"
                else "Ethereum transactions moving at least "
                f"{LARGE_TRANSFER_MIN['ETH']:,} ETH directly (sender and recipient; value "
                "moved by internal contract calls is not included)"
            )
            + ". event_time = block time.",
        )
    btc_day = "during the UTC day (Bitcoin, Blockchair aggregation)"
    out[("coin_days_destroyed", "BTC")] = _daily(
        "whale.coin_days_destroyed.btc.1d",
        "coin_days_destroyed",
        "coin_days",
        _DAY_CLOSED,
        f"Coin days destroyed by all transactions {btc_day}: Σ spent BTC × days since each was "
        "received.",
    )
    out[("revived_supply_1y", "BTC")] = _daily(
        "whale.revived_supply_1y.btc.1d",
        "revived_supply_1y",
        "btc",
        _DAY_CLOSED,
        f"BTC spent {btc_day} from outputs at least 365 days old (dormant coins moving).",
    )
    out[("lth_spent_155d", "BTC")] = _daily(
        "whale.lth_spent_155d.btc.1d",
        "lth_spent_155d",
        "btc",
        _DAY_CLOSED,
        f"BTC spent {btc_day} from outputs at least 155 days old (long-term holder spending, "
        "by coin age).",
    )
    out[("miner_origin_spent", "BTC")] = _daily(
        "whale.miner_origin_spent.btc.1d",
        "miner_origin_spent",
        "btc",
        _DAY_CLOSED,
        f"BTC spent {btc_day} from coinbase outputs (first movement of newly mined coins).",
    )
    return out


DATASETS: dict[tuple[str, str], DatasetSpec] = _per_asset()

FAMILY: dict[str, Family] = {
    "exchange_inflow": "exchange",
    "exchange_outflow": "exchange",
    "exchange_supply": "exchange",
    "supply": "network",
    "issuance": "network",
    "coin_days_destroyed": "dormancy",
    "revived_supply_1y": "dormancy",
    "lth_spent_155d": "dormancy",
    "miner_origin_spent": "miner",
    "address_balance": "balance",
    "large_transfer": "transfer",
}


def dataset(metric: str, asset: str) -> DatasetSpec:
    try:
        return DATASETS[(metric, asset)]
    except KeyError:
        raise KeyError(f"no whale dataset {metric!r} for {asset}") from None


def has_dataset(metric: str, asset: str) -> bool:
    return (metric, asset) in DATASETS


def all_datasets() -> list[DatasetSpec]:
    return list(DATASETS.values())


def dataset_by_id(dataset_id: str) -> DatasetSpec:
    for spec in DATASETS.values():
        if spec.dataset_id == dataset_id:
            return spec
    raise KeyError(dataset_id)


def key_of(dataset_id: str) -> tuple[str, str]:
    """(metric, asset) of a whale dataset id."""
    for key, spec in DATASETS.items():
        if spec.dataset_id == dataset_id:
            return key
    raise KeyError(dataset_id)
