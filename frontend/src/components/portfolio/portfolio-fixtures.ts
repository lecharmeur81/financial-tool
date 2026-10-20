/** Hand-written `portfolio_exposure.v0` responses for tests (shapes taken from the backend). */
import { type PortfolioExposure, parsePortfolioExposure } from "@/lib/portfolio";

const UNAVAILABLE = [
  {
    id: "PF-UNV-HOLDINGS",
    what: "Real holdings and account balances",
    reason:
      "The platform has no account, exchange or wallet connection and stores no real holdings.",
  },
  {
    id: "PF-UNV-SECTOR",
    what: "Sector exposure",
    reason: "No sector classification data is available.",
  },
  {
    id: "PF-UNV-CORRELATION",
    what: "Return correlation",
    reason: "No return-correlation computation or methodology exists yet.",
  },
];

const NOT_CLAIMED = [
  {
    id: "PF-NOT-REAL-HOLDINGS",
    text: "These are simulated paper trades. They are not real holdings, balances or positions on any exchange.",
  },
  {
    id: "PF-NO-TRADING",
    text: "This service places no orders and connects to no exchange or trading account.",
  },
];

const CONVENTIONS = [
  "Positions are simulated paper trades (status open), not real holdings.",
  "Notional is the position size fixed at entry, in USD. It is not marked to market.",
];

/** Two valid positions (BTC long vs a bearish brief; ETH short, no brief), one missing price, one invalid. */
export function populatedRaw(): Record<string, unknown> {
  return {
    contract_version: "portfolio_exposure.v0",
    source: {
      kind: "simulated_paper_trades",
      label: "Simulated paper trades (status open). Not real holdings.",
      positions_received: 3,
      positions_valid: 2,
      positions_invalid: 1,
    },
    conventions: CONVENTIONS,
    summary: {
      status: "computed",
      gross_notional: "1500",
      long_notional: "1000",
      short_notional: "500",
      net_notional: "500",
      total_margin: "1000",
      notional_weighted_leverage: "1.666667",
      asset_count: 2,
      largest_asset: "BTC",
      largest_asset_share: "0.666667",
      concentration_hhi: "0.555556",
    },
    assets: [
      {
        asset: "BTC",
        position_count: 1,
        net_direction: "long",
        brief: {
          status: "assessed",
          stance: "Bearish",
          confidence: "Medium",
          posture: "Defensive",
          decision_state: "candidate_unresolved",
          snapshot_as_of: "2026-10-20T00:00:00Z",
          snapshot_row_id: 9,
        },
        brief_relation: "opposite_direction",
        disagreement: true,
        long_notional: "1000",
        short_notional: "0",
        gross_notional: "1000",
        net_notional: "1000",
        share_of_gross: "0.666667",
      },
      {
        asset: "ETH",
        position_count: 1,
        net_direction: "short",
        brief: { status: "not_assessed", reason: "No Advisor Brief was available for this asset." },
        brief_relation: "not_assessed",
        disagreement: null,
        long_notional: "0",
        short_notional: "500",
        gross_notional: "500",
        net_notional: "-500",
        share_of_gross: "0.333333",
      },
    ],
    positions: [
      {
        trade_id: "t1",
        asset: "BTC",
        direction: "long",
        notional: "1000",
        leverage: "2",
        margin: "500",
        price_status: "ok",
        brief_relation: "opposite_direction",
        disagreement: true,
      },
      {
        trade_id: "t2",
        asset: "ETH",
        direction: "short",
        notional: "500",
        leverage: "1",
        margin: "500",
        price_status: "missing",
        brief_relation: "not_assessed",
        disagreement: null,
      },
    ],
    invalid_positions: [{ trade_id: "t3", reasons: ["unknown_asset"] }],
    data_quality: {
      positions_missing_price: 1,
      assets_without_assessed_brief: ["ETH"],
      has_gaps: true,
    },
    unavailable: UNAVAILABLE,
    not_claimed: NOT_CLAIMED,
  };
}

/** No open paper trades at all. */
export function emptyRaw(): Record<string, unknown> {
  return {
    contract_version: "portfolio_exposure.v0",
    source: {
      kind: "simulated_paper_trades",
      label: "Simulated paper trades (status open). Not real holdings.",
      positions_received: 0,
      positions_valid: 0,
      positions_invalid: 0,
    },
    conventions: CONVENTIONS,
    summary: {
      status: "empty",
      gross_notional: "0",
      long_notional: "0",
      short_notional: "0",
      net_notional: "0",
      total_margin: "0",
      notional_weighted_leverage: null,
      asset_count: 0,
      largest_asset: null,
      largest_asset_share: null,
      concentration_hhi: null,
    },
    assets: [],
    positions: [],
    invalid_positions: [],
    data_quality: {
      positions_missing_price: 0,
      assets_without_assessed_brief: [],
      has_gaps: false,
    },
    unavailable: UNAVAILABLE,
    not_claimed: NOT_CLAIMED,
  };
}

export function parsed(raw: Record<string, unknown>): PortfolioExposure {
  const out = parsePortfolioExposure(raw);
  if (!out) throw new Error("fixture does not parse");
  return out;
}
