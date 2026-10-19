"""``portfolio_exposure.v0``: exposure and concentration of SIMULATED open paper trades.

Phase 54 step 1 (ADR-0095). A pure function: no database, network, clock or Claude call. The
inputs are open ``usr.paper_trade`` rows (Phase 24) and compact Advisor Brief summaries (Phase 53);
the output is a description, never an instruction.

Verified meaning of the inputs (``cfi.paper``):

- An open position is a ``usr.paper_trade`` row with ``status = 'open'``. It is a hypothetical trade
  the user logged; the platform has no exchange or wallet connection, so it is **not** a holding.
- ``notional`` is the simulated position size in USD, fixed at entry (``entry_price_execution`` is
  when it was priced). This view does **not** mark it to market.
- ``leverage`` is a positive multiplier and ``margin = notional / leverage`` (USD of capital at
  risk), stored at creation. Dollar P&L never depends on leverage; this view does not use P&L.
- ``direction`` is ``long`` or ``short``.

Conventions (stated in the response as well):

- Signed notional: ``long = +notional``, ``short = -notional``. ``gross = sum(notional)``,
  ``net = sum(signed notional)``.
- Asset share = asset gross notional / portfolio gross notional. The shares of the valid positions
  sum to 1. ``largest_asset_share`` is their maximum and ``concentration_hhi`` is the sum of the
  squared shares (1/n for n equal assets, 1 for a single asset). These describe the simulated
  portfolio only; they are not a risk verdict and have no threshold.
- ``notional_weighted_leverage = sum(notional * leverage) / sum(notional)``.
- A position with unusable data (unknown asset or direction, non-finite or non-positive notional or
  leverage, a margin that is missing, negative or not ``notional / leverage``) is excluded from
  every metric and listed under ``invalid_positions``. It is never repaired or guessed.
- ``price_status`` records only whether the platform currently has a price for the asset. A missing
  price flags the position; it does not change the notional-based metrics.

Advisor Brief comparison (descriptive only; ``disagreement`` is a transparency flag):

- The brief's stance is compared with a position's direction. A bullish stance (Strongly Bullish,
  Bullish, Cautiously Bullish) with a long position, or a bearish stance with a short position, is
  ``same_direction``; the reverse is ``opposite_direction`` (``disagreement = True``).
- ``Neutral / Wait`` is ``stance_neutral``; ``Insufficient Evidence`` is ``no_directional_view``;
  neither is agreement nor disagreement (``disagreement = None``). A missing or unusable brief, or
  an unrecognised stance, is ``not_assessed``. Missing is never treated as neutral.
- At asset level the position direction is the sign of the asset's net notional; a zero net is
  ``no_net_direction``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any, Final

__all__ = [
    "CONTRACT_VERSION",
    "NOT_CLAIMED",
    "UNAVAILABLE",
    "build_exposure",
    "summarize_brief",
]

CONTRACT_VERSION: Final = "portfolio_exposure.v0"

DIRECTIONS: Final = ("long", "short")
BULLISH: Final = frozenset({"Strongly Bullish", "Bullish", "Cautiously Bullish"})
BEARISH: Final = frozenset({"Strongly Bearish", "Bearish", "Cautiously Bearish"})
NEUTRAL: Final = "Neutral / Wait"
INSUFFICIENT: Final = "Insufficient Evidence"

CONVENTIONS: Final[tuple[str, ...]] = (
    "Positions are simulated paper trades (status open), not real holdings.",
    "Signed notional: long is positive, short is negative. Gross is the sum of notionals; net is "
    "the sum of signed notionals.",
    "Notional is the position size fixed at entry, in USD. It is not marked to market.",
    "Asset share is the asset's gross notional divided by the portfolio's gross notional.",
    "concentration_hhi is the sum of squared asset shares; it has no threshold and no verdict.",
    "notional_weighted_leverage is sum(notional x leverage) / sum(notional).",
    "A disagreement flag compares a position's direction with the Advisor Brief's stance. It is "
    "descriptive, not an instruction.",
)

UNAVAILABLE: Final[tuple[dict[str, str], ...]] = (
    {
        "id": "PF-UNV-HOLDINGS",
        "what": "Real holdings and account balances",
        "reason": "The platform has no account, exchange or wallet connection and stores no real "
        "holdings.",
    },
    {
        "id": "PF-UNV-SECTOR",
        "what": "Sector exposure",
        "reason": "No sector classification data is available.",
    },
    {
        "id": "PF-UNV-CORRELATION",
        "what": "Return correlation",
        "reason": "No return-correlation computation or methodology exists yet.",
    },
    {
        "id": "PF-UNV-LIQUIDITY",
        "what": "Portfolio-level liquidity",
        "reason": "Execution depth and position liquidity are not measured.",
    },
    {
        "id": "PF-UNV-VERDICT",
        "what": "Suitability or overexposure verdict",
        "reason": "The platform does not know the user's goals, horizon or risk tolerance, and "
        "sets no exposure thresholds.",
    },
)

NOT_CLAIMED: Final[tuple[dict[str, str], ...]] = (
    {
        "id": "PF-NOT-REAL-HOLDINGS",
        "text": "These are simulated paper trades. They are not real holdings, balances or "
        "positions on any exchange.",
    },
    {
        "id": "PF-NOT-ADVICE",
        "text": "This is general context. It is not personalized financial advice and gives no "
        "trading instruction of any kind.",
    },
    {
        "id": "PF-NOT-PREDICTION",
        "text": "Nothing here predicts a price or an outcome, and nothing here shows that any "
        "position or stance is profitable.",
    },
    {
        "id": "PF-NO-TRADING",
        "text": "This service places no orders and connects to no exchange or trading account.",
    },
    {
        "id": "PF-UNAVAILABLE-IS-NOT-NEUTRAL",
        "text": "A missing brief, missing price or unusable position is reported as such. It is "
        "never counted as neutral, agreeing or safe.",
    },
)

_SHARE_PLACES: Final = Decimal("0.000001")


def _txt(value: Decimal, places: Decimal | None = None) -> str:
    """Decimal as a string, so no float rounding can alter a figure on the wire."""
    if places is not None:
        value = value.quantize(places)
    return format(value, "f")


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def summarize_brief(brief: Mapping[str, Any]) -> dict[str, Any]:
    """The few Advisor Brief fields this view uses, copied verbatim; nothing is recomputed."""
    return {
        "status": "assessed",
        "stance": brief["assessment"]["stance"]["final"],
        "confidence": brief["assessment"]["stance"]["confidence"],
        "posture": brief["assessment"]["stance"]["posture"],
        "decision_state": brief["assessment"]["investment_state"]["decision_state"],
        "snapshot_as_of": brief["snapshot"].get("as_of"),
        "snapshot_row_id": brief["snapshot"].get("row_id"),
    }


def _not_assessed(reason: str) -> dict[str, Any]:
    return {"status": "not_assessed", "reason": reason}


def _usable_brief(brief: Mapping[str, Any] | None) -> dict[str, Any]:
    if brief is None:
        return _not_assessed("No Advisor Brief was available for this asset.")
    if brief.get("status") != "assessed":
        reason = brief.get("reason")
        return _not_assessed(reason if isinstance(reason, str) and reason else "Not assessed.")
    out = {k: brief.get(k) for k in ("stance", "confidence", "posture", "decision_state")}
    if not isinstance(out["stance"], str) or not out["stance"]:
        return _not_assessed("The Advisor Brief carried no usable stance.")
    return {
        "status": "assessed",
        **out,
        "snapshot_as_of": brief.get("snapshot_as_of"),
        "snapshot_row_id": brief.get("snapshot_row_id"),
    }


def _relation(sign: int, brief: Mapping[str, Any]) -> tuple[str, bool | None]:
    """(relation, disagreement) of a direction sign (+1 long, -1 short, 0 none) and a brief."""
    if brief["status"] != "assessed":
        return "not_assessed", None
    stance = brief["stance"]
    if stance == INSUFFICIENT:
        return "no_directional_view", None
    if stance == NEUTRAL:
        return "stance_neutral", None
    if stance in BULLISH:
        lean = 1
    elif stance in BEARISH:
        lean = -1
    else:
        return "not_assessed", None  # an unrecognised stance is never read as a lean
    if sign == 0:
        return "no_net_direction", None
    return ("same_direction", False) if sign == lean else ("opposite_direction", True)


def _validate(
    position: Mapping[str, Any], assets: Iterable[str]
) -> tuple[dict[str, Any] | None, list[str]]:
    reasons: list[str] = []
    asset = position.get("asset")
    direction = position.get("direction")
    if asset not in set(assets):
        reasons.append("unknown_asset")
    if direction not in DIRECTIONS:
        reasons.append("unknown_direction")
    notional = _dec(position.get("notional"))
    leverage = _dec(position.get("leverage"))
    margin = _dec(position.get("margin"))
    if notional is None or notional <= 0:
        reasons.append("invalid_notional")
    if leverage is None or leverage <= 0:
        reasons.append("invalid_leverage")
    if margin is None or margin < 0:
        reasons.append("invalid_margin")
    elif (
        notional is not None
        and notional > 0
        and leverage is not None
        and leverage > 0
        and abs(margin - notional / leverage) > Decimal("0.000001") * notional
    ):
        reasons.append("margin_inconsistent_with_notional_and_leverage")
    if reasons or notional is None or leverage is None or margin is None:
        return None, reasons or ["malformed_position"]
    return {
        "trade_id": str(position.get("trade_id")),
        "asset": str(asset),
        "direction": str(direction),
        "notional": notional,
        "leverage": leverage,
        "margin": margin,
        "price_status": "missing" if position.get("price_status") == "missing" else "ok",
    }, []


def build_exposure(
    positions: Sequence[Mapping[str, Any]],
    briefs: Mapping[str, Mapping[str, Any] | None],
    assets: Sequence[str],
) -> dict[str, Any]:
    """Compose ``portfolio_exposure.v0``. Inputs are never mutated; same inputs, same output."""
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    for position in positions:
        parsed, reasons = _validate(position, assets)
        if parsed is None:
            invalid.append({"trade_id": str(position.get("trade_id")), "reasons": reasons})
        else:
            valid.append(parsed)
    valid.sort(key=lambda p: (p["asset"], p["trade_id"]))
    invalid.sort(key=lambda p: p["trade_id"])

    gross = sum((p["notional"] for p in valid), Decimal(0))
    long_n = sum((p["notional"] for p in valid if p["direction"] == "long"), Decimal(0))
    short_n = gross - long_n
    margin_total = sum((p["margin"] for p in valid), Decimal(0))

    by_asset: dict[str, list[dict[str, Any]]] = {}
    for p in valid:
        by_asset.setdefault(p["asset"], []).append(p)

    asset_rows: list[dict[str, Any]] = []
    for asset, items in by_asset.items():
        a_long = sum((p["notional"] for p in items if p["direction"] == "long"), Decimal(0))
        a_short = sum((p["notional"] for p in items if p["direction"] == "short"), Decimal(0))
        a_gross = a_long + a_short
        a_net = a_long - a_short
        sign = (a_net > 0) - (a_net < 0)
        brief = _usable_brief(briefs.get(asset))
        relation, disagreement = _relation(sign, brief)
        asset_rows.append(
            {
                "asset": asset,
                "position_count": len(items),
                "long_notional": a_long,
                "short_notional": a_short,
                "gross_notional": a_gross,
                "net_notional": a_net,
                "net_direction": {1: "long", -1: "short", 0: "none"}[sign],
                "share_of_gross": a_gross / gross,
                "brief": brief,
                "brief_relation": relation,
                "disagreement": disagreement,
            }
        )
    asset_rows.sort(key=lambda r: (-r["gross_notional"], r["asset"]))

    position_rows: list[dict[str, Any]] = []
    for p in valid:
        brief = _usable_brief(briefs.get(p["asset"]))
        relation, disagreement = _relation(1 if p["direction"] == "long" else -1, brief)
        position_rows.append(
            {
                "trade_id": p["trade_id"],
                "asset": p["asset"],
                "direction": p["direction"],
                "notional": _txt(p["notional"]),
                "leverage": _txt(p["leverage"]),
                "margin": _txt(p["margin"]),
                "price_status": p["price_status"],
                "brief_relation": relation,
                "disagreement": disagreement,
            }
        )

    if not positions:
        status = "empty"
    elif not valid:
        status = "no_valid_positions"
    else:
        status = "computed"

    summary: dict[str, Any] = {
        "status": status,
        "gross_notional": _txt(gross),
        "long_notional": _txt(long_n),
        "short_notional": _txt(short_n),
        "net_notional": _txt(long_n - short_n),
        "total_margin": _txt(margin_total),
        "notional_weighted_leverage": None,
        "asset_count": len(asset_rows),
        "largest_asset": None,
        "largest_asset_share": None,
        "concentration_hhi": None,
    }
    if gross > 0:
        summary["notional_weighted_leverage"] = _txt(
            sum((p["notional"] * p["leverage"] for p in valid), Decimal(0)) / gross, _SHARE_PLACES
        )
        summary["largest_asset"] = asset_rows[0]["asset"]
        summary["largest_asset_share"] = _txt(asset_rows[0]["share_of_gross"], _SHARE_PLACES)
        summary["concentration_hhi"] = _txt(
            sum((r["share_of_gross"] ** 2 for r in asset_rows), Decimal(0)), _SHARE_PLACES
        )

    assets_out = [
        {
            **{k: v for k, v in r.items() if k not in {"share_of_gross", *_DEC_KEYS}},
            **{k: _txt(r[k]) for k in _DEC_KEYS},
            "share_of_gross": _txt(r["share_of_gross"], _SHARE_PLACES),
        }
        for r in asset_rows
    ]

    not_assessed = sorted(r["asset"] for r in asset_rows if r["brief"]["status"] != "assessed")
    return {
        "contract_version": CONTRACT_VERSION,
        "source": {
            "kind": "simulated_paper_trades",
            "label": "Simulated paper trades (status open). Not real holdings.",
            "positions_received": len(positions),
            "positions_valid": len(valid),
            "positions_invalid": len(invalid),
        },
        "conventions": list(CONVENTIONS),
        "summary": summary,
        "assets": assets_out,
        "positions": position_rows,
        "invalid_positions": invalid,
        "data_quality": {
            "positions_missing_price": sum(1 for p in valid if p["price_status"] == "missing"),
            "assets_without_assessed_brief": not_assessed,
            "has_gaps": bool(
                invalid or not_assessed or any(p["price_status"] == "missing" for p in valid)
            ),
        },
        "unavailable": [dict(u) for u in UNAVAILABLE],
        "not_claimed": [dict(n) for n in NOT_CLAIMED],
    }


_DEC_KEYS: Final = ("long_notional", "short_notional", "gross_notional", "net_notional")
