import type { DecisionAsset, DecisionCurrent, DomainReading } from "@/lib/decision";

const NO_FRESHNESS = {
  status_counts: {},
  latest: null,
  expected_latest: null,
  rule: null,
  note: null,
};

export const ASSET_SPECIFIC = { code: "asset_specific", text: "Asset-specific" };
export const MARKET_WIDE = { code: "market_wide", text: "Market-wide" };
export const BENCHMARKED = {
  code: "market_wide_btc_benchmarked",
  text: "Market-wide (BTC-benchmarked)",
};

const missingDomain = (
  domain: string,
  scope_label: DomainReading["scope_label"],
  reasons: DomainReading["reasons"],
  freshness_info: DomainReading["freshness_info"] = NO_FRESHNESS,
): DomainReading => ({
  domain,
  component: `${domain}.score`,
  role: "Directional",
  scope_label,
  status: "insufficient_data",
  freshness: "no_data",
  evidence_state: "insufficient_data",
  quality_flags: [],
  direction: "U",
  strength: null,
  band: null,
  freshness_info,
  reasons,
});

const SCORE_REASON =
  "Insufficient data: available components carry weight 0 of 1.00 (minimum 0.5).";

/** The live data state: four domains with no data, each with the snapshot's explicit reasons. */
export function insufficientDecision(asset: DecisionAsset = "BTC"): DecisionCurrent {
  return {
    contract_version: "decision_view.v0",
    asset,
    stance: {
      final: "Insufficient Evidence",
      raw: "Insufficient Evidence",
      confidence: "Insufficient Evidence",
      posture: "INVESTIGATE FURTHER",
      differs_from_raw: false,
      cap_u_applied: false,
      headline: "Insufficient data.",
    },
    why: {
      directional: [
        { id: "STANCE.Insufficient Evidence", text: "Insufficient data." },
        { id: "DIR.whale.S1", text: "Large wallets are currently adding to their holdings." },
        { id: "DIR.macro.U", text: "We cannot currently describe the broader economic backdrop." },
      ],
      limits: [],
      missing_context: [
        { id: "DIR.macro.U", text: "We cannot currently describe the broader economic backdrop." },
      ],
    },
    cap_u: [],
    observed_caps: [],
    evidence: {
      supportive: [
        {
          side: "supportive",
          domain: "whale",
          scope_label: ASSET_SPECIFIC,
          strength: "Moderate",
          band: "accumulation",
          text: "Large wallets are currently adding to their holdings.",
          template_id: "DIR.whale.S1",
          quality_flags: ["partial"],
          field_ids: ["get_whale_activity.assets[0].score"],
        },
      ],
      adverse: [],
      neutral: [],
    },
    conflict: { directional: false, contradictions: [], conflicting_tools: [] },
    risks: [{ dimension: "market", level: "Low", text: "Market risk reads low." }],
    max_risk: "Low",
    coverage: {
      available: 1,
      expected: 5,
      missing: ["institutional", "liquidity", "macro", "market_structure"],
      missing_context: ["regime"],
    },
    domains: [
      missingDomain(
        "institutional",
        ASSET_SPECIFIC,
        [{ kind: "freshness_note", text: "no ETF data stored", path: "p.freshness.note" }],
        {
          status_counts: { no_data: 1 },
          latest: null,
          expected_latest: "2026-10-02",
          rule: null,
          note: "no ETF data stored",
        },
      ),
      {
        domain: "whale",
        component: "whale.score",
        role: "Directional",
        scope_label: ASSET_SPECIFIC,
        status: "ok",
        freshness: "fresh",
        evidence_state: "available",
        quality_flags: [],
        direction: "S",
        strength: "Moderate",
        band: "accumulation",
        freshness_info: NO_FRESHNESS,
        reasons: [],
      },
      missingDomain("liquidity", MARKET_WIDE, [
        { kind: "score_reason", text: SCORE_REASON, path: "liq.score.reason" },
        {
          kind: "component_reason",
          text: "no circulating-supply snapshot for USDT",
          path: "liq.s",
        },
      ]),
      missingDomain("macro", MARKET_WIDE, [
        { kind: "component_reason", text: "no VIX value near as_of", path: "macro.vix.reason" },
      ]),
      missingDomain("market_structure", BENCHMARKED, []),
    ],
    scope_notes: [],
    limitations: [],
    data_quality: {
      unavailable_components: ["institutional.score", "macro.score"],
      stale_components: [],
      partial_components: ["whale.score"],
      not_assessed_components: ["derivatives.band"],
      unavailable_tools: [],
      degraded_tools: [],
      look_ahead_violations: [],
      platform_limits: ["Meme assets are tracked only as a retail-attention proxy."],
    },
    snapshot: {
      row_id: 467,
      uuid: "4c79f753-0ef7-4766-b131-406452df8ffd",
      row_created_at: "2026-10-05T23:10:00+00:00",
      as_of: "2026-10-05T23:09:52.212066+00:00",
      knowledge_time: "2026-10-05T23:09:52.212066+00:00",
      snapshot_version: "analyst_snapshot.v1",
      producer_payload_hash: "a".repeat(64),
      producer_hash_check: "verified",
      decision_input_hash: "b".repeat(64),
    },
    methodology: {
      methodology_version: "decision_methodology.v0",
      parameter_version: "decision_params.v0",
      template_version: "decision_templates.v0",
      fired_rule_ids: ["DS-01"],
      confidence_rule_ids: ["CF-01"],
      posture_rule_id: "PO-01",
    },
    technical: {
      fields: [
        {
          field_id: "get_macro.score.status",
          display: "insufficient_data",
          evidence_category: null,
          quality_status: null,
          unit: null,
          source: null,
        },
      ],
      fields_without_display: 2,
    },
  };
}

/** A complete, bullish assessment with one adverse item. */
export function bullishDecision(): DecisionCurrent {
  const base = insufficientDecision();
  return {
    ...base,
    stance: {
      final: "Bullish",
      raw: "Bullish",
      confidence: "Moderate",
      posture: "MONITOR WITH ELEVATED CAUTION",
      differs_from_raw: false,
      cap_u_applied: false,
      headline: "More of the available evidence leans supportive than adverse.",
    },
    why: {
      directional: [
        { id: "STANCE.Bullish", text: "More of the available evidence leans supportive." },
        { id: "DIR.institutional.S2", text: "Money is flowing into US spot funds strongly." },
      ],
      limits: [],
      missing_context: [],
    },
    evidence: {
      supportive: [
        {
          side: "supportive",
          domain: "institutional",
          scope_label: ASSET_SPECIFIC,
          strength: "Strong",
          band: "strong net inflow",
          text: "Money is flowing into US spot funds strongly.",
          template_id: "DIR.institutional.S2",
          quality_flags: [],
          field_ids: [],
        },
      ],
      adverse: [
        {
          side: "adverse",
          domain: "liquidity",
          scope_label: MARKET_WIDE,
          strength: "Moderate",
          band: "contracting",
          text: "Stablecoin supply is shrinking.",
          template_id: "DIR.liquidity.A1",
          quality_flags: [],
          field_ids: [],
        },
      ],
      neutral: [],
    },
    coverage: { available: 5, expected: 5, missing: [], missing_context: [] },
    domains: [],
    data_quality: { ...base.data_quality, unavailable_components: [], partial_components: [] },
  };
}

/** Raw bullish evidence limited by CAP-U to a more conservative final stance. */
export function cappedDecision(): DecisionCurrent {
  const base = bullishDecision();
  return {
    ...base,
    stance: {
      final: "Neutral / Wait",
      raw: "Bullish",
      confidence: "Low",
      posture: "WAIT",
      differs_from_raw: true,
      cap_u_applied: true,
      headline: "The evidence is limited.",
    },
    cap_u: [
      {
        rule_id: "CU-01",
        cap_source: "regime",
        source_field_id: "get_market_regime.regime_id",
        binding: true,
        raw_stance: "Bullish",
        applied_ceiling: "Neutral / Wait",
        final_stance: "Neutral / Wait",
        final_posture: "WAIT",
        text: "The market regime could not be read, so the stance is held at neutral.",
        template_id: "CAPU.CU-01",
      },
    ],
  };
}

/** Independent evidence pointing in different directions (not missing data). */
export function conflictedDecision(): DecisionCurrent {
  const base = bullishDecision();
  return {
    ...base,
    stance: { ...base.stance, final: "Neutral / Wait", raw: "Neutral / Wait", posture: "WAIT" },
    conflict: { directional: true, contradictions: ["regime_disagrees"], conflicting_tools: [] },
  };
}

export function forAsset(decision: DecisionCurrent, asset: DecisionAsset): DecisionCurrent {
  return { ...decision, asset };
}
