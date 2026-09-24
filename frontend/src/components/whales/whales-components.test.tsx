import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Metric, Source } from "@/lib/institutional";
import type { Classification, Contradiction, Holders, Transfers, WhaleScore } from "@/lib/whales";

import { ClassificationCell } from "./ClassificationCell";
import { ContradictionPanel } from "./ContradictionPanel";
import { HoldersPanel } from "./HoldersPanel";
import { TransfersPanel } from "./TransfersPanel";
import { WhaleScoreCard } from "./WhaleScoreCard";

afterEach(cleanup);

const source: Source = {
  provider_id: "coinmetrics",
  provider_name: "Coin Metrics Community",
  original_source: "coinmetrics",
  dataset_id: "whale.exchange_inflow.btc.1d",
  enabled: true,
  terms_verified: true,
  attribution: {
    text: "Source: Coin Metrics Community Network Data (CC BY-NC 4.0)",
    url: "https://coinmetrics.io/community-network-data/",
  },
};

const freshness = {
  status: "fresh" as const,
  latest: "2026-09-09",
  expected_latest: "2026-09-09",
  age_seconds: null,
  rule: "newest day ≥ latest day due",
  note: "up to date",
};

const quality = {
  status: "ok",
  days_expected: 7,
  days_present: 7,
  flagged: 0,
  revised: 0,
  backfilled: 0,
  estimated_availability: 3,
  notes: [],
};

const metric = (overrides: Partial<Metric> = {}): Metric => ({
  metric_id: "exchange_netflow_7d_pct_exchange_supply.v1",
  label: "Net flow to exchanges, last 7 days",
  evidence_category: "metric",
  evidence_class: "attributed",
  value: "-0.2506",
  unit: "% of exchange supply",
  timestamp: "2026-09-09",
  calculation: "(140,000.00 in − 147,000.00 out) BTC … = −0.2506 %",
  source,
  freshness,
  quality,
  ...overrides,
});

const binance: Classification = {
  address: "34xp4vRoCGJym3xR7yCVPFHoCNxv4Twseo",
  chain: "bitcoin",
  actor_class: "exchange",
  display: "Known exchange: Binance",
  entity_id: "binance",
  entity_name: "Binance",
  evidence_class: "attributed",
  confidence: "0.6",
  evidence:
    'BitInfoCharts top-100 list shows this address with the wallet label "Binance-coldwallet"',
  source: "BitInfoCharts",
  source_url: "https://bitinfocharts.com/top-100-richest-bitcoin-addresses.html",
  rule: "label (attributed)",
  conflicting_labels: [],
};

const unknown: Classification = {
  ...binance,
  address: "1BoatSLRHtKNngkdXEeobR76b53LETtpyT",
  actor_class: "unknown_large_holder",
  display: "Unknown large holder",
  entity_id: null,
  entity_name: null,
  evidence_class: "inferred",
  confidence: "0.5",
  evidence:
    "No label. Balance 10,100.00 BTC ≥ 1,000 BTC (size only: says nothing about who controls the address)",
  source: "size rule",
  source_url: null,
  rule: "size rule: balance ≥ 1,000 BTC",
};

const score: WhaleScore = {
  score_id: "whale_flow_score",
  version: "v1",
  asset: "BTC",
  as_of: "2026-09-10T12:00:00Z",
  knowledge_time: "2026-09-10T12:00:00Z",
  evidence_category: "metric",
  status: "ok",
  value: "22.5",
  unit: "points (−100 … +100)",
  band: "accumulation",
  reason: null,
  available_weight: "1.00",
  calculation: "score = 100 × Σ(weight × sub-score) ÷ Σ(weights of available components)",
  window_end: "2026-09-09",
  components: [
    {
      component_id: "exchange_netflow_7d",
      status: "ok",
      reason: null,
      definition: "Σ (inflow − outflow) …",
      evidence: "Calculated metric from attributed evidence",
      weight: "0.35",
      effective_weight: "0.3500",
      reference_scale: "1.0",
      sub_score: "0.2506",
      contribution: "8.77",
      window: { start: "2026-09-03", end: "2026-09-09" },
      inputs: {},
      metric: metric(),
    },
    {
      component_id: "large_holders_7d",
      status: "unavailable",
      reason: "no snapshot 7 days (± 1 day) before the latest one",
      definition: "…",
      evidence: "Calculated metric from inferred evidence (size only — owners unknown)",
      weight: "0.25",
      effective_weight: null,
      reference_scale: "1.0",
      sub_score: null,
      contribution: null,
      window: { start: null, end: "2026-09-10" },
      inputs: {},
      metric: metric({ value: null, evidence_class: "inferred", label: "Unknown large holders" }),
    },
  ],
  contradictions: [],
  miner_spending: null,
  interpretation_limits: ["An address is not an owner."],
  bands_note: "Bands …",
};

const contradictions: Contradiction[] = [
  {
    indicator_id: "exchange_flows_vs_old_coins",
    label: "Exchange flows vs old coins moving",
    status: "contradiction",
    explanation: "Net flow to exchanges points to accumulation, old coins to distribution.",
    readings: [
      {
        label: "Net flow",
        value: "0.2506",
        unit: "sub-score",
        direction: "accumulation",
        source: "Coin Metrics",
      },
      {
        label: "Old coins",
        value: "-0.5000",
        unit: "sub-score",
        direction: "distribution",
        source: "Blockchair",
      },
    ],
  },
  {
    indicator_id: "whales_vs_etf",
    label: "Whale flow score vs Institutional Flow Score",
    status: "insufficient_data",
    explanation: "Insufficient data: Institutional Flow Score.",
    readings: [
      {
        label: "Whale",
        value: "22.5",
        unit: "score",
        direction: "accumulation",
        source: "this page",
      },
      { label: "ETF", value: null, unit: "score", direction: "unknown", source: "Phase 6" },
    ],
  },
];

describe("whale components", () => {
  it("shows the score, every component and why a component is excluded", () => {
    render(<WhaleScoreCard score={score} />);
    expect(screen.getByLabelText("score value").textContent).toContain("+22.5");
    expect(screen.getByText("accumulation")).toBeTruthy();
    expect(screen.getByText("excluded")).toBeTruthy();
    expect(screen.getByText(/no snapshot 7 days/)).toBeTruthy();
    expect(screen.getAllByText(/Coin Metrics Community/).length).toBeGreaterThan(0);
  });

  it("says Insufficient data instead of a number", () => {
    render(
      <WhaleScoreCard
        score={{
          ...score,
          status: "insufficient_data",
          value: null,
          band: null,
          reason: "Insufficient data: weight 0.25",
        }}
      />,
    );
    expect(screen.getByRole("status").textContent).toContain("Insufficient data");
  });

  it("lists contradictions with both readings and their sources", () => {
    render(
      <ContradictionPanel items={contradictions} rule="Opposite directions = contradiction." />,
    );
    const row = screen.getByText("Exchange flows vs old coins moving").closest("tr")!;
    expect(within(row).getByText("Contradiction")).toBeTruthy();
    expect(within(row).getByText(/→ distribution/)).toBeTruthy();
    expect(screen.getByText("Insufficient data")).toBeTruthy();
  });

  it("shows evidence, source and confidence of a classification", () => {
    render(<ClassificationCell c={binance} />);
    expect(screen.getByText("Known exchange: Binance")).toBeTruthy();
    expect(screen.getByText(/Binance-coldwallet/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "BitInfoCharts" })).toBeTruthy();
    expect(screen.getByText("0.6")).toBeTruthy();
    expect(screen.getByText("attributed evidence")).toBeTruthy();
  });

  it("never presents a size-only address as a known entity", () => {
    render(<ClassificationCell c={unknown} />);
    expect(screen.getByText("Unknown large holder").className).toContain("badge-neutral");
    expect(screen.getByText(/says nothing about who controls/)).toBeTruthy();
    expect(screen.getByText("inferred evidence")).toBeTruthy();
  });

  it("flags conflicting labels", () => {
    render(
      <ClassificationCell
        c={{
          ...binance,
          conflicting_labels: [
            {
              actor_class: "fund",
              entity_id: "f1",
              evidence_class: "attributed",
              confidence: "0.4",
              source: "Other",
            },
          ],
        }}
      />,
    );
    expect(screen.getByText("conflicting labels")).toBeTruthy();
    expect(screen.getByText(/fund f1/)).toBeTruthy();
  });

  it("lists holders with cohorts and a note when no earlier balance exists", () => {
    const holders: Holders = {
      asset: "BTC",
      unit: "btc",
      snapshot: "2026-09-10T06:00:00Z",
      compared_with: "2026-09-03T06:00:00Z",
      compared_note: null,
      definition: "Balance of each of the 100 largest bitcoin addresses.",
      source: { ...source, provider_id: "blockchair", provider_name: "Blockchair" },
      label_sources: ["BitInfoCharts"],
      freshness,
      holders: [
        {
          rank: 1,
          balance: "245000",
          change_7d: "-5000",
          change_7d_note: null,
          classification: binance,
        },
        {
          rank: 2,
          balance: "900",
          change_7d: null,
          change_7d_note: "not in the top 100 seven days earlier",
          classification: {
            ...unknown,
            actor_class: "unlabelled",
            display: "Unlabelled",
            evidence_class: null,
            confidence: null,
            source: null,
          },
        },
      ],
      cohorts: [
        {
          actor_class: "exchange",
          label: "Known exchange",
          addresses: 1,
          balance: "245000",
          change_7d: "-5000",
          change_7d_pct: "-2.0000",
          change_7d_addresses_compared: 1,
          change_7d_addresses_left: 0,
          calculation: "…",
        },
      ],
      last_run: null,
    };
    render(<HoldersPanel holders={holders} />);
    expect(screen.getAllByText("−5,000")).toHaveLength(2); // cohort and holder row
    expect(screen.getByText("−2.0000 %")).toBeTruthy();
    expect(screen.getByText("not in the top 100 seven days earlier")).toBeTruthy();
  });

  it("shows transfers with flagged quality and missing senders explained", () => {
    const transfers: Transfers = {
      asset: "BTC",
      unit: "btc",
      range: { start: "2026-09-03T12:00:00Z", end: "2026-09-10T12:00:00Z" },
      threshold: "500",
      definition: "Bitcoin transaction outputs of at least 500 BTC.",
      source: { ...source, provider_id: "blockchair", provider_name: "Blockchair" },
      summary: {
        transfers: 2,
        total: "1800",
        by_direction: [
          { direction: "to_exchange", transfers: 1, total: "1200" },
          { direction: "other", transfers: 1, total: "600" },
        ],
        note: "Bitcoin outputs have no sender.",
      },
      transfers: [
        {
          time: "2026-09-10T09:00:00Z",
          tx_hash: "a".repeat(64),
          output_index: 0,
          value: "600",
          value_usd: null,
          direction: "other",
          sender: null,
          recipient: null,
          quality_status: "suspect",
          quality_note: "recipient is not a valid bitcoin address",
        },
      ],
      truncated: false,
      last_run: null,
    };
    render(<TransfersPanel transfers={transfers} />);
    expect(screen.getByText("suspect")).toBeTruthy();
    expect(screen.getByText("To labelled exchange")).toBeTruthy();
    expect(screen.getByText("not part of an output record")).toBeTruthy();
    expect(screen.getByText(/no valid address/)).toBeTruthy();
  });
});
