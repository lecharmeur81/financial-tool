import Link from "next/link";

import { Unavailable } from "@/components/dashboard/Unavailable";
import {
  ADVISOR_ASSETS,
  type AdvisorAsset,
  type AdvisorBrief,
  INSUFFICIENT_STANCE,
  INSUFFICIENT_STATE,
  SIDE_LABEL,
  decisionStateLabel,
  fetchAdvisorBrief,
  gapKindLabel,
  invalidationResultLabel,
  isCleanInvalidation,
  isUsableState,
  layerLabel,
  readingStateLabel,
} from "@/lib/advisor";
import { domainLabel } from "@/lib/decision";
import { type ApiResult, formatUtc } from "@/lib/market";

function AssetSwitch({ asset }: { asset: AdvisorAsset }) {
  return (
    <nav aria-label="Advisor Brief asset" className="segmented">
      {ADVISOR_ASSETS.map((a) => (
        <Link
          key={a}
          href={`/advisor?asset=${a}`}
          className={a === asset ? "segment active" : "segment"}
          aria-current={a === asset ? "page" : undefined}
        >
          {a}
        </Link>
      ))}
    </nav>
  );
}

function Frame({ asset, children }: { asset: AdvisorAsset; children: React.ReactNode }) {
  return (
    <section className="status-card decision-center" aria-labelledby="advisor-title">
      <header className="decision-header">
        <div>
          <h2 id="advisor-title">Advisor Brief — {asset}</h2>
          <p className="muted">
            A deterministic, rule-based summary of the latest stored evidence snapshot. General
            market context only — not a prediction, not personalized advice, and no trade is placed.
          </p>
        </div>
        <AssetSwitch asset={asset} />
      </header>
      <nav aria-label="Related views" className="related-links" data-testid="advisor-related">
        <Link href="/portfolio">Paper Portfolio Exposure</Link>
        <Link href={`/?asset=${asset}`}>Dashboard Decision Center ({asset})</Link>
        <Link href="/alerts">Alerts</Link>
      </nav>
      {children}
    </section>
  );
}

function LayerTag({ layer, definition }: { layer: string; definition?: string }) {
  return (
    <span className={`kind-tag layer-tag layer-${layer}`} title={definition}>
      {layerLabel(layer)}
    </span>
  );
}

function TextList({ items }: { items: string[] }) {
  return (
    <ul className="note-list">
      {items.map((t, i) => (
        <li key={`${i}-${t}`}>{t}</li>
      ))}
    </ul>
  );
}

function errorPanel(result: Extract<ApiResult<AdvisorBrief>, { ok: false }>) {
  switch (result.status) {
    case 404:
      return (
        <div className="decision-callout" role="status" data-testid="advisor-error-404">
          <p>
            <strong>No assessment yet.</strong> No stored snapshot exists, so there is nothing to
            brief. Nothing is shown in its place.
          </p>
        </div>
      );
    case 422:
      return (
        <div className="decision-callout" role="status" data-testid="advisor-error-422">
          <p>
            <strong>Unsupported asset.</strong> {result.reason} Choose BTC, ETH, SOL or XRP.
          </p>
        </div>
      );
    case 503:
      return (
        <div role="alert" data-testid="advisor-error-503">
          <Unavailable
            what="Advisor Brief"
            reason={`The latest stored snapshot cannot be used. ${result.reason}`}
          />
        </div>
      );
    default:
      return (
        <div data-testid="advisor-error-other">
          <Unavailable
            what="Advisor Brief"
            reason={
              result.status === null ? result.reason : `${result.reason} (HTTP ${result.status})`
            }
          />
        </div>
      );
  }
}

function Assessment({ brief }: { brief: AdvisorBrief }) {
  const { stance, decision_state: state } = brief.assessment;
  const a = brief.assessment;
  const insufficientStance = stance.final === INSUFFICIENT_STANCE;
  const insufficientState = state === INSUFFICIENT_STATE;
  return (
    <div className="decision-stance" data-testid="advisor-assessment">
      <p>
        <LayerTag
          layer="deterministic_assessment"
          definition={brief.layers.deterministic_assessment}
        />{" "}
        <span className="muted">The engines&apos; own words, shown unchanged.</span>
      </p>
      <dl className="decision-tiles">
        <div className="decision-tile">
          <dt>Market stance</dt>
          <dd className="decision-value" data-testid="advisor-stance">
            {stance.final}
          </dd>
        </div>
        <div className="decision-tile">
          <dt>Evidence confidence</dt>
          <dd className="decision-value" data-testid="advisor-confidence">
            {stance.confidence}
          </dd>
        </div>
        <div className="decision-tile">
          <dt>Posture</dt>
          <dd className="decision-value" data-testid="advisor-posture">
            {stance.posture}
          </dd>
        </div>
        <div className="decision-tile">
          <dt>Investment decision state</dt>
          <dd className="decision-value" data-testid="advisor-decision-state">
            {decisionStateLabel(state)}
          </dd>
        </div>
      </dl>

      {insufficientStance || insufficientState ? (
        <div className="decision-callout" role="note" data-testid="advisor-insufficient">
          <p>
            <strong>Insufficient evidence is a valid result, not an error.</strong> It means the
            stored evidence does not reach far enough for the system to take a bullish or bearish
            view. It is not a hold, buy or sell recommendation, and it is not a hidden neutral
            reading — the areas that are missing are listed under data gaps.
          </p>
        </div>
      ) : null}

      {a.gated ? (
        <p className="decision-cap" role="note" data-testid="advisor-gated">
          <strong>Withheld.</strong> An integrity gate is triggered, so the investment decision was
          not assessed. {a.gate_reasons.join(", ")}
        </p>
      ) : null}

      {stance.cap_u_applied || stance.differs_from_raw ? (
        <p className="decision-cap" role="note" data-testid="advisor-capped">
          The final stance is more cautious than the underlying evidence
          {stance.raw ? ` (before limits: ${stance.raw})` : ""} because required evidence could not
          be evaluated.
        </p>
      ) : null}

      {stance.headline ? <p className="decision-headline">{stance.headline}</p> : null}
      {a.state_notice ? <p className="muted">{a.state_notice}</p> : null}
      {a.decision_reasons.length > 0 ? (
        <p className="muted">Decision-state reason codes: {a.decision_reasons.join(", ")}</p>
      ) : null}
      {a.why_directional.length + a.why_limits.length > 0 ? (
        <>
          <h3>Why?</h3>
          <TextList items={[...a.why_directional, ...a.why_limits]} />
        </>
      ) : null}
      <p className="muted">
        Evidence confidence describes how complete and consistent the evidence is. It is not a
        probability of any price move.
      </p>
    </div>
  );
}

function DataGaps({ brief }: { brief: AdvisorBrief }) {
  const { items, has_gaps: hasGaps } = brief.data_gaps;
  return (
    <section
      aria-labelledby="advisor-gaps-title"
      className="advisor-gaps"
      data-testid="advisor-gaps"
    >
      <h3 id="advisor-gaps-title">
        Data gaps <span className="badge badge-warn">{items.length}</span>
      </h3>
      {items.length === 0 && !hasGaps ? (
        <p className="muted">The brief reports no data gaps.</p>
      ) : items.length === 0 ? (
        <p>
          <span className="badge badge-warn">Gaps reported</span> The brief says gaps exist but
          lists none. Treat the evidence as incomplete.
        </p>
      ) : (
        <>
          <p className="muted">
            Missing, stale, partial or unassessed evidence is a gap. It is never counted as neutral,
            supportive or adverse.
          </p>
          <ul className="decision-missing">
            {items.map((g, i) => (
              <li key={`${g.kind}-${g.domain ?? g.ref ?? ""}-${i}`}>
                <span className="badge badge-warn">{gapKindLabel(g.kind)}</span>{" "}
                {g.domain ? <strong>{domainLabel(g.domain)}</strong> : null}
                {g.evidence_state ? (
                  <span className="badge badge-neutral">{readingStateLabel(g.evidence_state)}</span>
                ) : null}
                {g.ref ? <span className="muted"> {g.ref}</span> : null}
                {g.reasons.length > 0 ? <TextList items={g.reasons} /> : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Signals({ brief }: { brief: AdvisorBrief }) {
  return (
    <section aria-labelledby="advisor-signals-title">
      <h3 id="advisor-signals-title">Evidence the assessment used</h3>
      {brief.signals.length === 0 ? (
        <p className="muted" data-testid="advisor-no-signals">
          No evidence item was usable, so there are no signals to show. This is absence of evidence,
          not a neutral reading.
        </p>
      ) : (
        <ul className="decision-evidence" data-testid="advisor-signals">
          {brief.signals.map((s, i) => (
            <li key={`${s.domain}-${i}`}>
              <LayerTag layer={s.layer} definition={brief.layers[s.layer]} />{" "}
              <span className="badge badge-neutral">{SIDE_LABEL[s.side] ?? s.side}</span>{" "}
              <strong>{domainLabel(s.domain)}</strong>{" "}
              <span className="muted">
                scope: {s.scope ?? "not stated"}
                {s.strength !== null ? ` · strength ${s.strength}` : ""}
                {s.band ? ` · band ${s.band}` : ""}
              </span>
              {s.quality_flags.length > 0 ? (
                <span className="badge badge-warn">{s.quality_flags.join(", ")}</span>
              ) : null}
              <div>{s.text ?? <span className="muted">No description in the snapshot.</span>}</div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Readings({ brief }: { brief: AdvisorBrief }) {
  return (
    <section aria-labelledby="advisor-readings-title">
      <h3 id="advisor-readings-title">Every evidence area, with its data state</h3>
      <ul className="decision-missing" data-testid="advisor-readings">
        {brief.readings.map((r, i) => {
          const usable = isUsableState(r.evidence_state);
          return (
            <li key={`${r.domain}-${i}`} data-usable={usable ? "yes" : "no"}>
              <LayerTag layer={r.layer} definition={brief.layers[r.layer]} />{" "}
              <strong>{domainLabel(r.domain)}</strong>{" "}
              {r.role ? <span className="muted">({r.role})</span> : null}{" "}
              <span className={usable ? "badge badge-ok" : "badge badge-warn"}>
                {readingStateLabel(r.evidence_state)}
              </span>
              {r.freshness ? (
                <span className="badge badge-neutral">freshness: {r.freshness}</span>
              ) : null}
              {r.quality_flags.length > 0 ? (
                <span className="badge badge-warn">{r.quality_flags.join(", ")}</span>
              ) : null}
              {usable ? (
                <span className="muted">
                  {" "}
                  {r.direction ? `direction: ${r.direction}` : ""}
                  {r.band ? ` · band ${r.band}` : ""}
                </span>
              ) : (
                <div className="muted">Not usable as evidence — not counted as neutral.</div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function Risks({ brief }: { brief: AdvisorBrief }) {
  const r = brief.risk;
  const u = brief.uncertainty;
  return (
    <section aria-labelledby="advisor-risk-title">
      <h3 id="advisor-risk-title">Decision risks and limits</h3>
      <p>
        <LayerTag layer="risk_reading" definition={brief.layers.risk_reading} />{" "}
        <span className="muted">
          Highest decision risk: {r.max_decision_risk ?? "not stated"}. Risk readings are not
          directional evidence.
        </span>
      </p>
      {r.decision_risks.length === 0 ? (
        <p className="muted">No decision-risk readings were returned.</p>
      ) : (
        <ul className="note-list" data-testid="advisor-risks">
          {r.decision_risks.map((x, i) => (
            <li key={`${x.dimension}-${i}`}>
              <strong>{x.dimension}</strong> — {x.level}
              {x.text ? `: ${x.text}` : ""}
            </li>
          ))}
        </ul>
      )}
      {r.market_risks_detected.length > 0 ? (
        <>
          <h4>Market risks detected</h4>
          <TextList items={r.market_risks_detected} />
        </>
      ) : null}
      {u.directional_conflict ? (
        <p className="decision-cap" role="note">
          <strong>Conflicting evidence.</strong> Supportive and adverse evidence both exist.
        </p>
      ) : null}
      {u.contradictions.length > 0 ? <TextList items={u.contradictions} /> : null}
      {u.limitations.length > 0 ? (
        <>
          <h4>Current limitations</h4>
          <TextList items={u.limitations} />
        </>
      ) : null}
      {u.missing_context.length > 0 ? (
        <>
          <h4>Missing context</h4>
          <TextList items={u.missing_context} />
        </>
      ) : null}
      {u.scope_notes.length > 0 ? <TextList items={u.scope_notes} /> : null}
    </section>
  );
}

function Invalidation({ brief }: { brief: AdvisorBrief }) {
  const inv = brief.invalidation;
  return (
    <section aria-labelledby="advisor-invalidation-title" data-testid="advisor-invalidation">
      <h3 id="advisor-invalidation-title">What would invalidate it, and when it is reassessed</h3>
      {inv === null ? (
        <p>
          <span className="badge badge-warn">No invalidation conditions</span> None were returned
          for this asset (for example because nothing was assessed). That is not a statement that
          the assessment cannot be invalidated.
        </p>
      ) : (
        <>
          {inv.summary ? (
            <p>
              Overall:{" "}
              <span
                className={isCleanInvalidation(inv.summary) ? "badge badge-ok" : "badge badge-warn"}
              >
                {invalidationResultLabel(inv.summary)}
              </span>
            </p>
          ) : null}
          <ul className="note-list">
            {inv.conditions.map((c) => (
              <li key={c.condition_id}>
                <strong>{c.name}</strong>{" "}
                <span
                  className={isCleanInvalidation(c.result) ? "badge badge-ok" : "badge badge-warn"}
                >
                  {invalidationResultLabel(c.result)}
                </span>
                {c.meaning ? <div className="muted">{c.meaning}</div> : null}
              </li>
            ))}
          </ul>
        </>
      )}
      <h4>Reassessment</h4>
      {brief.reassessment.length === 0 ? (
        <p className="muted">No reassessment triggers were returned.</p>
      ) : (
        <ul className="note-list" data-testid="advisor-reassessment">
          {brief.reassessment.map((r, i) => (
            <li key={`${r.kind}-${i}`}>
              {r.kind.replace(/_/g, " ")}
              {r.when ? ` — ${r.when}` : ""}
              {r.ref ? <span className="muted"> ({r.ref})</span> : null}
              {r.evaluable === false ? (
                <span className="badge badge-warn">cannot be evaluated now</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function NotClaimed({ brief }: { brief: AdvisorBrief }) {
  return (
    <details className="decision-disclosure" data-testid="advisor-not-claimed">
      <summary>What this brief does not claim</summary>
      {brief.not_claimed.length === 0 ? (
        <p className="muted">
          The service returned no statements. Regardless, this is not a prediction, not personalized
          advice and not a trade.
        </p>
      ) : (
        <ul className="note-list">
          {brief.not_claimed.map((n) => (
            <li key={n.id}>{n.text}</li>
          ))}
        </ul>
      )}
    </details>
  );
}

function LayerKey({ brief }: { brief: AdvisorBrief }) {
  const entries = Object.entries(brief.layers);
  if (entries.length === 0) return null;
  return (
    <details className="decision-disclosure">
      <summary>How to read the layer labels</summary>
      <ul className="note-list">
        {entries.map(([k, def]) => (
          <li key={k}>
            <strong>{layerLabel(k)}</strong> — {def}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The Advisor Brief for an already-fetched result (pure; the fetching wrapper is below). */
export function AdvisorBriefView({
  result,
  asset,
}: {
  result: ApiResult<AdvisorBrief>;
  asset: AdvisorAsset;
}) {
  if (!result.ok) return <Frame asset={asset}>{errorPanel(result)}</Frame>;
  const brief = result.data;
  return (
    <Frame asset={asset}>
      <p className="muted" data-testid="advisor-observed">
        Snapshot as of {formatUtc(brief.snapshot.as_of)} · snapshot #{brief.snapshot.row_id ?? "—"}
      </p>
      {asset !== "BTC" ? (
        <p className="decision-scope-banner" role="note">
          {asset} is not a fully independent analysis: only some evidence is specific to {asset};
          the rest is market-wide or BTC-benchmarked. See each item&apos;s scope.
        </p>
      ) : null}
      <Assessment brief={brief} />
      <DataGaps brief={brief} />
      <Signals brief={brief} />
      <Readings brief={brief} />
      <Risks brief={brief} />
      <Invalidation brief={brief} />
      <LayerKey brief={brief} />
      <NotClaimed brief={brief} />
    </Frame>
  );
}

export async function AdvisorBriefSection({ asset }: { asset: AdvisorAsset }) {
  const result = await fetchAdvisorBrief(asset);
  return <AdvisorBriefView result={result} asset={asset} />;
}

export function AdvisorBriefLoading() {
  return (
    <section className="status-card decision-center" aria-busy="true">
      <h2>Advisor Brief</h2>
      <p className="muted" role="status">
        Loading the latest brief…
      </p>
    </section>
  );
}
