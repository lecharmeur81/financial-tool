import type { Metadata } from "next";
import { connection } from "next/server";

import type { EvidenceItem } from "@/lib/brief";
import { fetchLatestBrief } from "@/lib/brief";
import { formatUtc } from "@/lib/market";
import { navItem } from "@/lib/navigation";

const item = navItem("/brief");

export const metadata: Metadata = { title: item.label };

function EvidenceList({ items }: { items: EvidenceItem[] }) {
  if (!items.length) return <p className="muted">None.</p>;
  return (
    <ul className="note-list">
      {items.map((e, i) => (
        <li key={i}>
          {e.text}
          {e.field_ids.length ? <span className="muted"> ({e.field_ids.join(", ")})</span> : null}
        </li>
      ))}
    </ul>
  );
}

function StringList({ items }: { items: string[] }) {
  if (!items.length) return <p className="muted">None.</p>;
  return (
    <ul className="note-list">
      {items.map((s, i) => (
        <li key={i}>{s}</li>
      ))}
    </ul>
  );
}

export default async function BriefPage() {
  // Render at request time so the brief shown is never a build-time snapshot.
  await connection();
  const brief = await fetchLatestBrief();

  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>

      {!brief.ok ? (
        <div className="status-card" role="alert">
          <span className="badge badge-error">Daily brief unavailable</span>{" "}
          <span>{brief.reason}</span>
        </div>
      ) : !brief.data.response ? (
        <div className="status-card">
          <p className="muted">
            Insufficient data. No completed brief with a response is available (status:{" "}
            {brief.data.status}).
          </p>
        </div>
      ) : (
        (() => {
          const r = brief.data.response;
          return (
            <div className="status-card">
              <p className="muted">
                Reporting period {formatUtc(brief.data.reporting_period_start)} …{" "}
                {formatUtc(brief.data.reporting_period_end)} · model {brief.data.model ?? "—"} ·
                prompt {brief.data.prompt_version ?? "—"} · data quality{" "}
                {brief.data.data_quality_state ?? "—"}
              </p>

              <h2>Summary</h2>
              <p>{r.summary}</p>

              <h2>Evidence</h2>
              <EvidenceList items={r.evidence} />

              <h2>Contradicting Evidence</h2>
              <EvidenceList items={r.contradicting_evidence} />

              <h2>Market Regime</h2>
              <p>{r.market_regime}</p>

              <h2>Key Changes</h2>
              <h3>Macro</h3>
              <EvidenceList items={r.key_changes.macro} />
              <h3>Market structure</h3>
              <EvidenceList items={r.key_changes.market_structure} />
              <h3>Divergences</h3>
              <EvidenceList items={r.key_changes.divergences} />
              <h3>Anomalies</h3>
              <EvidenceList items={r.key_changes.anomalies} />
              <h3>Capital rotation</h3>
              <EvidenceList items={r.key_changes.capital_rotation} />

              <h2>Capital Participant Behavior</h2>
              <h3>Institutional</h3>
              <EvidenceList items={r.capital_participant_behavior.institutional} />
              <h3>Whale</h3>
              <EvidenceList items={r.capital_participant_behavior.whale} />
              <h3>Retail</h3>
              <EvidenceList items={r.capital_participant_behavior.retail} />

              <h2>Derivatives &amp; Liquidity Context</h2>
              <h3>Derivatives</h3>
              <EvidenceList items={r.derivatives_liquidity_context.derivatives} />
              <h3>Liquidity</h3>
              <EvidenceList items={r.derivatives_liquidity_context.liquidity} />

              <h2>Historical Context</h2>
              <EvidenceList items={r.historical_context} />

              <h2>Risks &amp; Uncertainties</h2>
              <StringList items={r.risks_uncertainties} />

              <h2>Scenarios</h2>
              {r.scenarios.length ? (
                r.scenarios.map((s, i) => (
                  <details key={i} className="component-details" open>
                    <summary>{s.label}</summary>
                    <p>{s.description}</p>
                    <p className="muted">Supporting evidence</p>
                    <EvidenceList items={s.supporting_evidence} />
                    <p className="muted">Contradicting evidence</p>
                    <EvidenceList items={s.contradicting_evidence} />
                    <p className="muted">Strengthening conditions</p>
                    <StringList items={s.strengthening_conditions} />
                    <p className="muted">Invalidation conditions</p>
                    <StringList items={s.invalidation_conditions} />
                  </details>
                ))
              ) : (
                <p className="muted">None.</p>
              )}

              <h2>Invalidation Conditions</h2>
              <StringList items={r.invalidation_conditions} />

              <h2>Data Quality</h2>
              <p>{r.data_quality}</p>

              {brief.data.validation_errors?.length ? (
                <>
                  <h2>Validation notes</h2>
                  <StringList items={brief.data.validation_errors} />
                </>
              ) : null}
            </div>
          );
        })()
      )}
    </section>
  );
}
