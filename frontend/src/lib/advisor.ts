/**
 * Advisor Brief client (Phase 53 step 2): a read-only view of `GET /api/v1/advisor/brief`.
 *
 * The browser never calls the API (ADR-0015): this runs on the server through `getJson`. Nothing
 * here decides, scores or recomputes — stance, confidence, posture, decision state and every
 * invalidation result are the engine's own words, shown unchanged. An unexpected response shape is
 * refused (never rendered half-trusted), and missing evidence is never turned into a neutral value.
 */
import { type ApiResult, getJson } from "@/lib/market";

export const ADVISOR_ASSETS = ["BTC", "ETH", "SOL", "XRP"] as const;
export type AdvisorAsset = (typeof ADVISOR_ASSETS)[number];

export const ADVISOR_CONTRACT = "advisor_brief.v0";

export type AdvisorStance = {
  final: string;
  raw: string | null;
  confidence: string;
  posture: string;
  headline: string | null;
  differs_from_raw: boolean;
  cap_u_applied: boolean;
};

export type AdvisorSignal = {
  layer: string;
  side: string;
  domain: string;
  scope: string | null;
  strength: string | number | null;
  band: string | null;
  text: string | null;
  quality_flags: string[];
  field_ids: string[];
};

export type AdvisorReading = {
  layer: string;
  domain: string;
  role: string | null;
  evidence_state: string;
  status: string | null;
  freshness: string | null;
  direction: string | null;
  strength: string | number | null;
  band: string | null;
  quality_flags: string[];
};

export type AdvisorGap = {
  kind: string;
  domain: string | null;
  evidence_state: string | null;
  ref: string | null;
  reasons: string[];
};

export type AdvisorRisk = { dimension: string; level: string; text: string | null };

export type AdvisorCondition = {
  condition_id: string;
  name: string;
  meaning: string | null;
  result: string;
};

export type AdvisorReassessment = {
  kind: string;
  ref: string | null;
  when: string | null;
  evaluable: boolean | null;
};

export type AdvisorBrief = {
  contract_version: string;
  asset: string;
  snapshot: { as_of: string | null; row_id: number | string | null };
  layers: Record<string, string>;
  assessment: {
    stance: AdvisorStance;
    why_directional: string[];
    why_limits: string[];
    decision_state: string;
    investment_status: string | null;
    gated: boolean;
    gate_reasons: string[];
    decision_reasons: string[];
    state_notice: string | null;
  };
  signals: AdvisorSignal[];
  readings: AdvisorReading[];
  uncertainty: {
    directional_conflict: boolean | null;
    contradictions: string[];
    limited_by_caps: boolean;
    limitations: string[];
    scope_notes: string[];
    missing_context: string[];
  };
  data_gaps: { has_gaps: boolean; items: AdvisorGap[] };
  risk: {
    decision_risks: AdvisorRisk[];
    max_decision_risk: string | null;
    market_risks_detected: string[];
  };
  invalidation: { summary: string | null; conditions: AdvisorCondition[] } | null;
  reassessment: AdvisorReassessment[];
  not_claimed: { id: string; text: string }[];
};

// --------------------------------------------------------------------------- guarded parsing

type Obj = Record<string, unknown>;
const isObj = (v: unknown): v is Obj => typeof v === "object" && v !== null && !Array.isArray(v);
const str = (v: unknown): string | null => (typeof v === "string" ? v : null);
const scalar = (v: unknown): string | number | null =>
  typeof v === "string" || typeof v === "number" ? v : null;
const strList = (v: unknown): string[] =>
  Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
const objList = (v: unknown): Obj[] => (Array.isArray(v) ? v.filter(isObj) : []);

/**
 * Validates the response and returns it in a closed shape, or `null` if a field the page depends
 * on is absent or of the wrong type. Nothing is defaulted into a value that looks like evidence:
 * a missing stance, confidence, posture or decision state makes the whole response unusable.
 */
export function parseAdvisorBrief(raw: unknown): AdvisorBrief | null {
  if (!isObj(raw) || raw.contract_version !== ADVISOR_CONTRACT) return null;
  const a = raw.assessment;
  if (!isObj(a) || !isObj(a.stance) || !isObj(a.investment_state)) return null;
  const stance = a.stance;
  const inv = a.investment_state;
  const final = str(stance.final);
  const confidence = str(stance.confidence);
  const posture = str(stance.posture);
  const decisionState = str(inv.decision_state);
  const asset = str(raw.asset);
  if (!final || !confidence || !posture || !decisionState || !asset) return null;
  if (!isObj(raw.data_gaps) || !Array.isArray(raw.data_gaps.items)) return null;
  if (!Array.isArray(raw.signals) || !Array.isArray(raw.readings)) return null;
  if (!isObj(raw.risk) || !isObj(raw.uncertainty) || !isObj(raw.layers)) return null;
  if (!Array.isArray(raw.not_claimed) || !Array.isArray(raw.reassessment)) return null;
  if (raw.invalidation != null && !isObj(raw.invalidation)) return null;

  const why = isObj(a.why) ? a.why : {};
  const snap = isObj(raw.snapshot) ? raw.snapshot : {};
  const unc = raw.uncertainty;
  const risk = raw.risk;
  const inval = isObj(raw.invalidation) ? raw.invalidation : null;
  const rowId = snap.row_id;

  return {
    contract_version: raw.contract_version,
    asset,
    snapshot: {
      as_of: str(snap.as_of),
      row_id: typeof rowId === "number" || typeof rowId === "string" ? rowId : null,
    },
    layers: Object.fromEntries(
      Object.entries(raw.layers).filter(([, v]) => typeof v === "string"),
    ) as Record<string, string>,
    assessment: {
      stance: {
        final,
        raw: str(stance.raw),
        confidence,
        posture,
        headline: str(stance.headline),
        differs_from_raw: stance.differs_from_raw === true,
        cap_u_applied: stance.cap_u_applied === true,
      },
      why_directional: strList(why.directional),
      why_limits: strList(why.limits),
      decision_state: decisionState,
      investment_status: str(inv.status),
      gated: inv.gated === true,
      gate_reasons: strList(inv.gate_reasons),
      decision_reasons: strList(inv.decision_reasons),
      state_notice: str(a.state_notice),
    },
    signals: objList(raw.signals).map((s) => ({
      layer: str(s.layer) ?? "context_reading",
      side: str(s.side) ?? "unknown",
      domain: str(s.domain) ?? "unknown",
      scope: str(s.scope),
      strength: scalar(s.strength),
      band: str(s.band),
      text: str(s.text),
      quality_flags: strList(s.quality_flags),
      field_ids: strList(s.field_ids),
    })),
    readings: objList(raw.readings).map((r) => ({
      layer: str(r.layer) ?? "context_reading",
      domain: str(r.domain) ?? "unknown",
      role: str(r.role),
      // an absent state is "unknown", which the page treats as NOT available
      evidence_state: str(r.evidence_state) ?? "unknown",
      status: str(r.status),
      freshness: str(r.freshness),
      direction: str(r.direction),
      strength: scalar(r.strength),
      band: str(r.band),
      quality_flags: strList(r.quality_flags),
    })),
    uncertainty: {
      directional_conflict:
        typeof unc.directional_conflict === "boolean" ? unc.directional_conflict : null,
      contradictions: strList(unc.contradictions),
      limited_by_caps: unc.limited_by_caps === true,
      limitations: strList(unc.limitations),
      scope_notes: strList(unc.scope_notes),
      missing_context: strList(unc.missing_context),
    },
    data_gaps: {
      has_gaps: raw.data_gaps.has_gaps !== false,
      items: objList(raw.data_gaps.items).map((g) => ({
        kind: str(g.kind) ?? "unknown",
        domain: str(g.domain),
        evidence_state: str(g.evidence_state),
        ref: str(g.ref) ?? str(g.reason_id),
        reasons: [...strList(g.reasons), ...(str(g.reason) ? [str(g.reason) as string] : [])],
      })),
    },
    risk: {
      decision_risks: objList(risk.decision_risks).map((r) => ({
        dimension: str(r.dimension) ?? "unknown",
        level: str(r.level) ?? "unknown",
        text: str(r.text),
      })),
      max_decision_risk: str(risk.max_decision_risk),
      market_risks_detected: strList(risk.market_risks_detected),
    },
    invalidation: inval
      ? {
          summary: str(inval.summary),
          conditions: objList(inval.conditions).map((c) => ({
            condition_id: str(c.condition_id) ?? "unknown",
            name: str(c.name) ?? "Unnamed condition",
            meaning: str(c.meaning),
            result: str(c.result) ?? "unknown",
          })),
        }
      : null,
    reassessment: objList(raw.reassessment).map((r) => ({
      kind: str(r.kind) ?? "unknown",
      ref: str(r.ref),
      when: str(r.when),
      evaluable: typeof r.evaluable === "boolean" ? r.evaluable : null,
    })),
    not_claimed: objList(raw.not_claimed).flatMap((n) => {
      const id = str(n.id);
      const text = str(n.text);
      return id && text ? [{ id, text }] : [];
    }),
  };
}

/**
 * `asset` is passed as a query parameter only after it is one of the four supported symbols; the
 * response is validated before any component sees it.
 */
export async function fetchAdvisorBrief(
  asset: AdvisorAsset = "BTC",
  fetchImpl?: typeof fetch,
): Promise<ApiResult<AdvisorBrief>> {
  const result = await getJson<unknown>("/api/v1/advisor/brief", { asset }, fetchImpl);
  if (!result.ok) return result;
  const brief = parseAdvisorBrief(result.data);
  if (!brief) {
    return {
      ok: false,
      status: null,
      reason:
        "The advisor service returned a response in an unexpected shape, so nothing is shown.",
    };
  }
  return { ok: true, data: brief };
}

export function resolveAdvisorAsset(
  query: Record<string, string | string[] | undefined>,
): AdvisorAsset {
  const raw = Array.isArray(query.asset) ? query.asset[0] : query.asset;
  const asset = raw?.toUpperCase() ?? "";
  return (ADVISOR_ASSETS as readonly string[]).includes(asset) ? (asset as AdvisorAsset) : "BTC";
}

// --------------------------------------------------------------------------- wording

/** Display names for the API's closed layer vocabulary. The API's definitions are shown beside. */
export const LAYER_LABEL: Record<string, string> = {
  observed_data: "Observed data",
  calculated_signal: "Calculated signal",
  regime_assessment: "Regime assessment",
  historical_analogue: "Historical analogue",
  hypothesis: "Hypothesis",
  risk_reading: "Risk reading",
  context_reading: "Context reading",
  deterministic_assessment: "Deterministic assessment",
};
export const layerLabel = (layer: string): string => LAYER_LABEL[layer] ?? layer.replace(/_/g, " ");

export const DECISION_STATE_LABEL: Record<string, string> = {
  withheld_integrity_gate: "Withheld (integrity gate)",
  candidate_invalidation_triggered: "Candidate: invalidation triggered",
  contradicted_evidence: "Contradicted evidence",
  insufficient_evidence: "Insufficient evidence",
  no_opportunity: "No opportunity identified",
  candidate_risk_findings_detected: "Candidate: risk findings detected",
  candidate_unresolved: "Candidate: unresolved checks",
  candidate_no_findings_detected: "Candidate: no findings detected",
};
export const decisionStateLabel = (s: string): string =>
  DECISION_STATE_LABEL[s] ?? s.replace(/_/g, " ");

export const GAP_KIND_LABEL: Record<string, string> = {
  reading_not_usable: "Evidence area not usable",
  missing_directional_domain: "Missing directional evidence",
  missing_context: "Missing context",
  unavailable_component: "Unavailable component",
  stale_component: "Stale component",
  partial_component: "Partial component",
  not_assessed_component: "Not assessed",
  unavailable_tool: "Unavailable tool",
  degraded_tool: "Degraded tool",
  look_ahead_violation: "Look-ahead violation",
  investment_state_not_conclusive: "Investment state not conclusive",
  investment_evidence_unusable: "Investment evidence unusable",
};
export const gapKindLabel = (k: string): string => GAP_KIND_LABEL[k] ?? k.replace(/_/g, " ");

export const READING_STATE_LABEL: Record<string, string> = {
  available: "Data available",
  available_freshness_not_assessed: "Available — freshness NOT assessed",
  insufficient_data: "Insufficient data",
  unavailable: "Unavailable",
  stale: "Stale",
  partial: "Partial",
  not_assessed: "Not assessed",
  not_applicable: "Not applicable",
  not_tracked: "Not tracked",
  unknown: "Unknown",
};
export const readingStateLabel = (s: string): string =>
  READING_STATE_LABEL[s] ?? s.replace(/_/g, " ");

/** Only these two states mean usable data. Everything else is a gap and is never shown as neutral. */
export const isUsableState = (s: string): boolean =>
  s === "available" || s === "available_freshness_not_assessed";

export const SIDE_LABEL: Record<string, string> = {
  supportive: "Supportive",
  adverse: "Adverse",
  neutral: "Neutral (evidence present, no lean)",
};

export const INVALIDATION_RESULT_LABEL: Record<string, string> = {
  triggered: "Triggered",
  not_triggered: "Not triggered",
  cannot_evaluate: "Cannot be evaluated",
  withheld: "Withheld (integrity gate)",
};

/** Only `not_triggered` is a clean result; every other value must stay visibly unresolved. */
export const isCleanInvalidation = (r: string): boolean => r === "not_triggered";
export const invalidationResultLabel = (r: string): string =>
  INVALIDATION_RESULT_LABEL[r] ?? r.replace(/_/g, " ");

/** The engine's own label for "not enough reliable evidence" (a valid outcome, not an error). */
export const INSUFFICIENT_STANCE = "Insufficient Evidence";
export const INSUFFICIENT_STATE = "insufficient_evidence";
