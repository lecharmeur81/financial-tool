import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AlertStatus } from "@/lib/alerts";
import type { AnomalyScan } from "@/lib/anomaly";
import type { BriefStatus } from "@/lib/brief";
import type { DerivativesAssetView } from "@/lib/derivatives";
import type { DivergenceMatrix } from "@/lib/divergence";
import type { Overview as InstitutionalOverview } from "@/lib/institutional";
import type { IntelligenceEvent } from "@/lib/intelligence";
import type { DecisionStatus } from "@/lib/journal";
import type { LiquidityOverview } from "@/lib/liquidity";
import type { MacroOverview } from "@/lib/macro";
import type { Summary } from "@/lib/market";
import type { OpenPositionStatus, PerformanceStats, TradeStatus } from "@/lib/paper";
import type { RegimeCurrent } from "@/lib/regime";
import type { RetailOverview } from "@/lib/retail";
import type { RotationMatrix } from "@/lib/rotation";
import type { WhaleScore } from "@/lib/whales";

import { AlertsSection } from "./AlertsSection";
import { AnomalySection } from "./AnomalySection";
import { BriefSection } from "./BriefSection";
import { DerivativesLiquiditySection } from "./DerivativesLiquiditySection";
import { DivergenceSection } from "./DivergenceSection";
import { IntelligenceEventsSection } from "./IntelligenceEventsSection";
import { IntelligenceOverviewSection } from "./IntelligenceOverviewSection";
import { JournalPaperSection } from "./JournalPaperSection";
import { MacroSection } from "./MacroSection";
import { MarketOverviewSection } from "./MarketOverviewSection";
import { ParticipantsSection } from "./ParticipantsSection";
import { RegimeSection } from "./RegimeSection";
import { RotationSection } from "./RotationSection";
import { Unavailable } from "./Unavailable";

afterEach(cleanup);

// --------------------------------------------------------------------------- fixtures

const regimeOk: RegimeCurrent = {
  asset: "BTC",
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  evidence_note: "note",
  regime_id: "leveraged_expansion",
  label: "Leveraged expansion",
  confidence: "0.62",
  confidence_semantic_note: "Confidence in the classification, not a probability of direction.",
  status: "ok",
  reason: null,
  held_by_hysteresis: false,
  regime_start_date: "2026-09-01",
  regime_duration_days: 30,
  regime_duration_capped: false,
  contributing_metrics: [
    {
      condition_id: "c1",
      label: "Funding elevated",
      metric_key: "funding",
      weight: "0.3",
      rationale: "Funding rate above threshold",
      value: "0.05",
      condition: "elevated",
    },
  ],
  contradicting_metrics: [],
  not_tracked: [],
};

describe("RegimeSection", () => {
  it("shows the classification, confidence semantic note, and supporting evidence", () => {
    render(<RegimeSection regime={regimeOk} />);
    expect(screen.getByText("Leveraged expansion")).toBeTruthy();
    expect(screen.getByText(/not a probability of direction/)).toBeTruthy();
    expect(screen.getByText(/Funding rate above threshold/)).toBeTruthy();
  });

  it("reports insufficient data rather than fabricating a label", () => {
    render(
      <RegimeSection regime={{ ...regimeOk, status: "insufficient_data", reason: "no data" }} />,
    );
    expect(screen.getByText(/Insufficient data/)).toBeTruthy();
  });
});

const summaryOk: Summary = {
  tool_id: "get_market_data",
  status: "ok",
  data: {
    as_of: "2026-10-01T00:00:00Z",
    assets: {
      BTC: {
        price_close: { value: "65000.00", unit: "usd", evidence_category: "observed_data" },
        change_24h_pct: { value: "1.50", unit: "pct", evidence_category: "calculated_metric" },
        change_7d_pct: { value: "3.00", unit: "pct", evidence_category: "calculated_metric" },
        volume_24h: { value: "1000", unit: "native", evidence_category: "observed_data" },
        realized_volatility_30d: {
          value: "0.45",
          unit: "annualized_ratio",
          evidence_category: "calculated_metric",
        },
      },
    },
  },
  error: null,
};

describe("MarketOverviewSection", () => {
  it("shows price, change, volume and volatility without recomputing them", () => {
    render(<MarketOverviewSection summary={summaryOk} structure={null} overview={null} />);
    expect(screen.getByText("$65,000")).toBeTruthy();
    expect(screen.getByText(/1\.50%/)).toBeTruthy();
  });

  it("reports insufficient data when the summary tool is unavailable", () => {
    render(
      <MarketOverviewSection
        summary={{
          tool_id: "get_market_data",
          status: "unavailable",
          data: null,
          error: { error_code: "no_data", detail: "no bars" },
        }}
        structure={null}
        overview={null}
      />,
    );
    expect(screen.getByText(/Insufficient data/)).toBeTruthy();
    expect(screen.getByText(/no bars/)).toBeTruthy();
  });
});

const institutionalOverview: InstitutionalOverview = {
  as_of: "2026-10-01T00:00:00Z",
  assets: [
    {
      asset: "BTC",
      score: {
        status: "ok",
        value: "70.0",
        band: "strong net inflow",
        reason: null,
        available_weight: "0.5",
      },
      latest_day: {
        date: "2026-09-30",
        net_flow_usd: "1000000",
        net_assets_usd: "1000000000",
        quality_status: "ok",
      },
      flow_5d: {
        status: "ok",
        net_flow_usd: "5000000",
        pct_of_net_assets: "0.5",
        window: { start: null, end: null },
        reason: null,
      },
      freshness: {
        status: "fresh",
        latest: null,
        expected_latest: null,
        age_seconds: 0,
        rule: "",
        note: "",
      },
    },
  ],
  source: {
    provider_id: "p",
    provider_name: "p",
    original_source: "p",
    dataset_id: "d",
    enabled: true,
    terms_verified: true,
    attribution: null,
  },
  interpretation_limits: [],
};

const whaleScoreOk: WhaleScore = {
  score_id: "whale_flow_score",
  version: "v1",
  asset: "BTC",
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  evidence_category: "metric",
  status: "ok",
  value: "40.0",
  unit: "points",
  band: "mild accumulation",
  reason: null,
  available_weight: "0.5",
  calculation: "calc",
  window_end: "2026-09-30",
  components: [],
  contradictions: [],
  miner_spending: null,
  interpretation_limits: [],
  bands_note: "note",
};

const retailOk: RetailOverview = {
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  evidence_note: "note",
  activity_score: {
    score_id: "retail_activity_score",
    version: "v1",
    calculated_at: "2026-10-01T00:00:00Z",
    evidence_category: "Calculated Metric",
    status: "ok",
    score: "55.0",
    band: "elevated",
    semantic_note: "note",
    reason: null,
  },
  speculation_score: {
    score_id: "retail_speculation_score",
    version: "v1",
    calculated_at: "2026-10-01T00:00:00Z",
    evidence_category: "Calculated Metric",
    status: "insufficient_data",
    score: null,
    band: null,
    semantic_note: "note",
    reason: "no data",
  },
  not_tracked: [],
};

describe("IntelligenceOverviewSection", () => {
  it("renders a compact tile per domain, linking to its full detail", () => {
    render(
      <IntelligenceOverviewSection
        institutional={institutionalOverview}
        whaleScore={whaleScoreOk}
        retail={retailOk}
        liquidity={null}
        derivatives={null}
        rotation={null}
      />,
    );
    expect(screen.getByText("Institutional (BTC)")).toBeTruthy();
    expect(screen.getByText("70.0")).toBeTruthy();
    expect(screen.getByText("Whales (BTC)")).toBeTruthy();
    expect(screen.getAllByText("Insufficient data").length).toBeGreaterThan(0);
  });
});

describe("ParticipantsSection", () => {
  it("keeps institutional, whale and retail visually distinct rather than merged", () => {
    render(
      <ParticipantsSection
        institutional={institutionalOverview}
        whaleScore={whaleScoreOk}
        retail={retailOk}
      />,
    );
    expect(screen.getByText("Institutional")).toBeTruthy();
    expect(screen.getByText("Whales")).toBeTruthy();
    expect(screen.getByText("Retail")).toBeTruthy();
    expect(screen.getByText("70.0")).toBeTruthy();
    expect(screen.getByText("40.0")).toBeTruthy();
    expect(screen.getByText("55.0")).toBeTruthy();
  });
});

const divergenceMatrixOk: DivergenceMatrix = {
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  window_days: 30,
  comparisons: [
    {
      comparison_id: "institutional_vs_price",
      number: 1,
      title: "Institutional flow vs. price",
      asset: "BTC",
      window_days: 30,
      as_of: "2026-10-01T00:00:00Z",
      knowledge_time: "2026-10-01T00:00:00Z",
      observed_quadrant: "flow_up_price_down",
      is_divergent: true,
      metric_a: {
        label: "Institutional flow",
        unit: "usd",
        status: "ok",
        reason: null,
        direction: "up",
        last_value: "1",
        change_pct: "1",
        historical_percentile: { status: "ok", percentile: "90", sample_size: 100 },
      },
      metric_b: {
        label: "Price",
        unit: "usd",
        status: "ok",
        reason: null,
        direction: "down",
        last_value: "1",
        change_pct: "-1",
        historical_percentile: { status: "ok", percentile: "10", sample_size: 100 },
      },
      duration: { days: 5, capped: false, since: "2026-09-26" },
      historical_examples: [],
      supporting_evidence: [],
      contradicting_evidence: [],
      notes: null,
      evidence_note: "note",
    },
  ],
  evidence_note: "note",
  not_tracked: [],
};

describe("DivergenceSection", () => {
  it("highlights divergent pairs without labelling them bullish or bearish", () => {
    render(<DivergenceSection matrix={{ ok: true, data: divergenceMatrixOk }} />);
    const row = screen.getByText("Institutional flow vs. price").closest("tr")!;
    expect(row).toBeTruthy();
    expect(within(row).queryByText(/bullish/i)).not.toBeTruthy();
    expect(within(row).queryByText(/bearish/i)).not.toBeTruthy();
  });

  it("shows Unavailable when the API call fails", () => {
    render(<DivergenceSection matrix={{ ok: false, reason: "Timed out" }} />);
    expect(screen.getByText("Divergences unavailable")).toBeTruthy();
  });
});

const anomalyScanOk: AnomalyScan = {
  asset: "BTC",
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  bands_version: "v1",
  anomalies: [
    {
      metric_id: "etf_flow",
      category: "institutional",
      label: "ETF net flow",
      asset: "BTC",
      unit: "usd",
      source: "sosovalue",
      evidence_class: "direct",
      proxy_caveat: null,
      timestamp: "2026-10-01T00:00:00Z",
      status: "ok",
      reason: null,
      current_value: "1000000",
      historical_percentile: { status: "ok", percentile: "97", sample_size: 365 },
      band: "extreme_high",
      magnitude: { value: "3.1", method: "z-score" },
      duration: { days: 2, capped: false, since: "2026-09-29" },
      possible_interpretations: ["Unusually large ETF inflow"],
      contradicting_evidence: [],
      data_quality: { status: "ok", points_considered: 365, flagged_points: 0 },
    },
  ],
  evidence_note: "note",
  not_tracked: [],
};

describe("AnomalySection", () => {
  it("surfaces only active (notable/extreme) bands by default", () => {
    render(<AnomalySection scan={{ ok: true, data: anomalyScanOk }} />);
    expect(screen.getByText("ETF net flow")).toBeTruthy();
    expect(screen.getByText("extreme_high")).toBeTruthy();
  });

  it("shows Unavailable when the API call fails", () => {
    render(<AnomalySection scan={{ ok: false, reason: "Unreachable" }} />);
    expect(screen.getByText("Anomalies unavailable")).toBeTruthy();
  });
});

const rotationMatrixOk: RotationMatrix = {
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  window_days: 30,
  pairs: [
    {
      from_node: {
        node_id: "btc",
        label: "BTC",
        measurement_class: "market_share",
        status: "ok",
        reason: null,
        direction: "up",
      },
      to_node: {
        node_id: "eth",
        label: "ETH",
        measurement_class: "market_share",
        status: "ok",
        reason: null,
        direction: "down",
      },
      window_days: 30,
      as_of: "2026-10-01T00:00:00Z",
      knowledge_time: "2026-10-01T00:00:00Z",
      observed_capital_flow: { from_node_direction: "up", to_node_direction: "down" },
      inferred_capital_rotation: {
        status: "possible_rotation",
        evidence_class: "inferred",
        hypothesis: "Capital may be rotating from ETH into BTC.",
      },
      duration: { days: 5, capped: false, since: "2026-09-26" },
      historical_examples: [],
      flow_corroboration: {
        supporting_evidence: ["ETF inflow to BTC"],
        contradicting_evidence: [],
      },
      evidence_note: "note",
    },
  ],
  evidence_note: "note",
  not_tracked: [],
};

describe("RotationSection", () => {
  it("keeps the inferred hypothesis labelled as not confirmed", () => {
    render(<RotationSection matrix={{ ok: true, data: rotationMatrixOk }} />);
    expect(screen.getByText(/Inferred — not confirmed/)).toBeTruthy();
    expect(screen.getByText(/rotating from ETH into BTC/)).toBeTruthy();
  });

  it("shows Unavailable when the API call fails", () => {
    render(<RotationSection matrix={{ ok: false, reason: "Unreachable" }} />);
    expect(screen.getByText("Capital rotation unavailable")).toBeTruthy();
  });
});

const derivativesView = {
  score: { status: "ok", health: "60.0", band: "balanced" },
  open_interest: { change_24h_pct: "2.5" },
} as unknown as DerivativesAssetView;

const liquidityOk: LiquidityOverview = {
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  evidence_note: "note",
  score: {
    score_id: "liquidity_score",
    version: "v1",
    calculated_at: "2026-10-01T00:00:00Z",
    evidence_category: "Calculated Metric",
    status: "ok",
    score: "30.0",
    band: "stable",
    semantic_note: "note",
    reason: null,
  },
  supply: {
    TOTAL: {
      subject: "TOTAL",
      status: "ok",
      reason: null,
      value: "1000",
      time: "2026-10-01T00:00:00Z",
      change_24h_pct: "0.1",
      change_7d_pct: "0.8",
      change_30d_pct: "2.0",
      condition: "growing",
    },
  },
  market_share: {},
  growth_acceleration: {
    status: "ok",
    reason: null,
    subject: "TOTAL",
    rate_now_7d_pct: "0.8",
    rate_prior_7d_pct: "0.5",
    change_pct_points: "0.3",
  },
  exchange_liquidity_change: { status: "unavailable", reason: "not tracked" },
  data_quality: { status: "ok" },
  not_tracked: [],
};

describe("DerivativesLiquiditySection", () => {
  it("shows derivatives health and liquidity growth side by side", () => {
    render(<DerivativesLiquiditySection derivatives={derivativesView} liquidity={liquidityOk} />);
    expect(screen.getByText("60.0")).toBeTruthy();
    expect(screen.getByText("30.0")).toBeTruthy();
    expect(screen.getByText(/0\.8%/)).toBeTruthy();
  });

  it("reports insufficient data when nothing is available", () => {
    render(<DerivativesLiquiditySection derivatives={null} liquidity={null} />);
    expect(screen.getAllByText("Insufficient data.").length).toBeGreaterThan(0);
  });
});

const macroOk: MacroOverview = {
  as_of: "2026-10-01T00:00:00Z",
  knowledge_time: "2026-10-01T00:00:00Z",
  evidence_note: "note",
  score: {
    score_id: "macro_environment_score",
    version: "v1",
    calculated_at: "2026-10-01T00:00:00Z",
    evidence_category: "Calculated Metric",
    status: "ok",
    score: "10.0",
    band: "neutral",
    semantic_note: "note",
    reason: null,
  },
  yield_curve: {
    status: "ok",
    reason: null,
    ust_10y_pct: "4.0",
    ust_2y_pct: "3.8",
    slope_pp: "0.2",
    time: "2026-10-01T00:00:00Z",
    condition: "normal",
    condition_reason: null,
  },
  real_policy_rate: {
    status: "ok",
    reason: null,
    value: "1.0",
    time: "2026-10-01T00:00:00Z",
    condition: "restrictive",
  },
  cpi_year_over_year: {
    status: "ok",
    reason: null,
    value: "3.0",
    time: "2026-10-01T00:00:00Z",
    condition: null,
  },
  vix: {
    status: "ok",
    reason: null,
    value: "15.0",
    time: "2026-10-01T00:00:00Z",
    condition: "calm",
  },
  equity_trend: {
    status: "ok",
    reason: null,
    value: "1.0",
    time: "2026-10-01T00:00:00Z",
    condition: "uptrend",
  },
  dollar_trend: {
    status: "insufficient_data",
    reason: "stale",
    value: null,
    time: null,
    condition: null,
  },
  oil_trend: {
    status: "ok",
    reason: null,
    value: "1.0",
    time: "2026-10-01T00:00:00Z",
    condition: "uptrend",
  },
  us_net_liquidity: { status: "ok", reason: null, value: "100", time: "2026-10-01T00:00:00Z" },
  us_net_liquidity_trend: {
    status: "ok",
    reason: null,
    value: "1.0",
    time: "2026-10-01T00:00:00Z",
    condition: "rising",
  },
  data_quality: { status: "ok" },
  not_tracked: [],
};

describe("MacroSection", () => {
  it("renders every macro series, calling out a stale one explicitly", () => {
    render(<MacroSection macro={{ ok: true, data: macroOk }} />);
    expect(screen.getByText("Yield curve (10y−2y)")).toBeTruthy();
    expect(screen.getByText("stale / unavailable")).toBeTruthy();
  });

  it("shows Unavailable when the API call fails", () => {
    render(<MacroSection macro={{ ok: false, reason: "Unreachable" }} />);
    expect(screen.getByText("Macro unavailable")).toBeTruthy();
  });
});

const alertOk: AlertStatus = {
  alert_id: "a1",
  alert_type: "metric_threshold",
  severity: "high",
  domain: "derivatives",
  trigger_condition: "funding_rate > 0.01",
  observed_value: "0.012",
  reference_value: "0.01",
  evidence_field_ids: ["f1"],
  snapshot_id: 1,
  source_tool_id: "get_derivatives",
  component_status: "ok",
  data_quality_state: "ok",
  status: "active",
  acknowledged_at: null,
  resolved_at: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

describe("AlertsSection", () => {
  it("lists alerts with an inline disclosure for details", () => {
    render(<AlertsSection alerts={{ ok: true, data: [alertOk] }} />);
    expect(screen.getByText(/funding_rate > 0.01/)).toBeTruthy();
  });

  it("shows an explicit empty state rather than nothing", () => {
    render(<AlertsSection alerts={{ ok: true, data: [] }} />);
    expect(screen.getByText("No alerts recorded.")).toBeTruthy();
  });

  it("shows Unavailable when the API call fails", () => {
    render(<AlertsSection alerts={{ ok: false, reason: "Unreachable" }} />);
    expect(screen.getByText("Alerts unavailable")).toBeTruthy();
  });
});

const briefOk: BriefStatus = {
  brief_id: "b1",
  status: "completed",
  reporting_period_start: "2026-09-30T00:00:00Z",
  reporting_period_end: "2026-10-01T00:00:00Z",
  prompt_version: "v1",
  analyst_version: "v1",
  model: "claude",
  response: {
    summary: "Institutional flows remain positive while retail activity is subdued.",
    evidence: [],
    contradicting_evidence: [],
    market_regime: "Leveraged expansion",
    key_changes: {
      macro: [],
      market_structure: [],
      divergences: [],
      anomalies: [],
      capital_rotation: [],
    },
    capital_participant_behavior: { institutional: [], whale: [], retail: [] },
    derivatives_liquidity_context: { derivatives: [], liquidity: [] },
    historical_context: [],
    risks_uncertainties: [],
    scenarios: [],
    invalidation_conditions: [],
    data_quality: "ok",
  },
  validation_status: "valid",
  validation_errors: null,
  attempt_count: 1,
  tools_called: [],
  data_quality_state: "ok",
  changes: null,
  error: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

describe("BriefSection", () => {
  it("shows the latest brief's own summary without reinterpreting it", () => {
    render(<BriefSection brief={{ ok: true, data: briefOk }} />);
    expect(screen.getByText(/Institutional flows remain positive/)).toBeTruthy();
    expect(screen.getByText("Read the complete brief →")).toBeTruthy();
  });

  it("shows Unavailable when the API call fails", () => {
    render(<BriefSection brief={{ ok: false, reason: "Unreachable" }} />);
    expect(screen.getByText("Daily brief unavailable")).toBeTruthy();
  });
});

const tradeOk: TradeStatus = {
  trade_id: "t1",
  asset: "BTC",
  direction: "long",
  status: "open",
  entry_time: "2026-10-01T00:00:00Z",
  entry_price_observed: "65000",
  notional: "1000",
  leverage: "1",
  exit_time: null,
  realized_pnl: null,
  return_pct: null,
  strategy_tag: null,
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

const positionOk: OpenPositionStatus = {
  trade: tradeOk,
  current_price_observed: "66000",
  unrealized_gross_pnl: "100",
  unrealized_net_pnl: "90",
  unrealized_return_pct: "1.5",
  data_quality_state: "ok",
};

const performanceOk: PerformanceStats = {
  total_trades: 10,
  open_trades: 1,
  closed_trades: 9,
  cancelled_trades: 0,
  winning_trades: 6,
  losing_trades: 3,
  win_rate: "0.67",
  gross_pnl: "500",
  net_pnl: "450",
  average_win: "100",
  average_loss: "-50",
  profit_factor: "2.0",
  expectancy: "45",
  max_drawdown: "-80",
  disclaimer: "Simulated performance on hypothetical trades.",
};

const decisionOk: DecisionStatus = {
  decision_id: "d1",
  decision_time: "2026-10-01T00:00:00Z",
  asset: "BTC",
  decision_type: "long",
  thesis: "Institutional accumulation while retail is quiet.",
  confidence: "0.6",
  status: "open",
  outcome: null,
  market_regime_label: "Leveraged expansion",
  created_at: "2026-10-01T00:00:00Z",
  updated_at: "2026-10-01T00:00:00Z",
};

describe("JournalPaperSection", () => {
  it("shows open positions, performance and recent decisions, linking to the full views", () => {
    render(
      <JournalPaperSection
        trades={{ ok: true, data: [tradeOk] }}
        positions={{ ok: true, data: [positionOk] }}
        performance={{ ok: true, data: performanceOk }}
        decisions={{ ok: true, data: [decisionOk] }}
      />,
    );
    expect(screen.getByText("450")).toBeTruthy();
    expect(screen.getByText(/BTC.*long.*open/)).toBeTruthy();
    expect(screen.getByText("Full paper trading →")).toBeTruthy();
    expect(screen.getByText("Full decision journal →")).toBeTruthy();
  });

  it("reports insufficient data per panel when a call fails, never mixing sources", () => {
    render(
      <JournalPaperSection
        trades={{ ok: false, reason: "Unreachable" }}
        positions={{ ok: false, reason: "Unreachable" }}
        performance={{ ok: false, reason: "Unreachable" }}
        decisions={{ ok: false, reason: "Unreachable" }}
      />,
    );
    expect(screen.getAllByText(/Insufficient data\./).length).toBeGreaterThanOrEqual(3);
  });
});

describe("Unavailable", () => {
  it("shows no cached or estimated values in place of missing data", () => {
    render(<Unavailable what="Something" reason="boom" />);
    expect(screen.getByText("Something unavailable")).toBeTruthy();
    expect(screen.getByText("boom")).toBeTruthy();
    expect(screen.getByText(/no cached or estimated values/)).toBeTruthy();
  });
});

const intelligenceEventsOk: IntelligenceEvent[] = [
  {
    event_id: "11111111-1111-1111-1111-111111111111",
    created_at: "2026-10-01T00:05:00Z",
    observed_at: "2026-10-01T00:00:00Z",
    domain: "regime",
    event_type: "regime_change",
    severity: "elevated",
    previous_value: "risk-off",
    current_value: "risk-on",
    change_magnitude: "1",
    detection_method: "rule_engine",
    data_quality_state: "ok",
    component_status: "ok",
    dedup_key: "regime:BTC",
    correlation_key: "regime:BTC:2026-10-01",
    snapshot_id: 42,
    status: "active",
    ai_interpretation_id: null,
  },
];

describe("IntelligenceEventsSection", () => {
  it("summarizes recent events and links to the full Analytics view", () => {
    render(<IntelligenceEventsSection events={{ ok: true, data: intelligenceEventsOk }} />);
    expect(screen.getByText(/elevated/)).toBeTruthy();
    expect(screen.getByText(/regime\/regime_change/)).toBeTruthy();
    expect(screen.getByText("All intelligence events →")).toBeTruthy();
  });

  it("shows no fabricated events when none are recorded", () => {
    render(<IntelligenceEventsSection events={{ ok: true, data: [] }} />);
    expect(screen.getByText(/No intelligence events recorded recently/)).toBeTruthy();
  });

  it("reports an unreachable API rather than hiding it", () => {
    render(<IntelligenceEventsSection events={{ ok: false, reason: "Unreachable" }} />);
    expect(screen.getByText("Intelligence events unavailable")).toBeTruthy();
  });
});
