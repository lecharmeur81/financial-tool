import {
  CONTRADICTION_LABEL,
  type DecisionCurrent,
  type EvidenceItem,
  RISK_DIMENSION_LABEL,
  domainLabel,
} from "@/lib/decision";

import { KindTag, ScopeTag } from "./shared";

function EvidenceList({ items, empty }: { items: EvidenceItem[]; empty: string }) {
  if (items.length === 0) return <p className="muted">{empty}</p>;
  return (
    <ul className="note-list decision-evidence">
      {items.map((item) => (
        <li key={`${item.domain}-${item.template_id ?? item.band ?? ""}`}>
          <strong>{domainLabel(item.domain)}</strong> <ScopeTag label={item.scope_label} />
          <div>
            <KindTag kind="interpretation" />{" "}
            {item.text ?? <span className="muted">{item.template_id}</span>}
          </div>
          {item.band ? (
            <div className="muted">
              <KindTag kind="calculated" /> {item.band} ({item.strength.toLowerCase()} reading
              {item.quality_flags.length ? `; ${item.quality_flags.join(", ")}` : ""})
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

/** Supporting evidence, contradicting/cautionary evidence and the main risks. */
export function EvidencePanels({ decision }: { decision: DecisionCurrent }) {
  const { evidence, conflict, risks, coverage } = decision;
  const hasMissing = coverage.missing.length > 0;
  return (
    <>
      <div className="decision-columns">
        <section aria-labelledby="decision-support-title">
          <h3 id="decision-support-title">Supporting evidence</h3>
          <EvidenceList
            items={evidence.supportive}
            empty="No supporting evidence is available right now."
          />
        </section>
        <section aria-labelledby="decision-adverse-title">
          <h3 id="decision-adverse-title">Contradicting or cautionary evidence</h3>
          {conflict.directional ? (
            <p role="note">
              <span className="badge badge-warn">Sources conflict</span> Independent evidence points
              in different directions.
              {conflict.contradictions.map((c) => (
                <span key={c}> {CONTRADICTION_LABEL[c] ?? c.replace(/_/g, " ")}</span>
              ))}
            </p>
          ) : null}
          <EvidenceList
            items={evidence.adverse}
            empty="No contradicting or cautionary evidence was found in the data that is available."
          />
          {hasMissing ? (
            <p className="muted">
              Missing evidence is not neutral and not zero — see what is missing, below.
            </p>
          ) : null}
        </section>
      </div>

      <section aria-labelledby="decision-risks-title">
        <h3 id="decision-risks-title">Main risks</h3>
        {risks.length === 0 ? (
          <p className="muted">No risk readings were produced.</p>
        ) : (
          <ul className="note-list">
            {risks.map((r) => (
              <li key={r.dimension}>
                <strong>{RISK_DIMENSION_LABEL[r.dimension] ?? r.dimension}:</strong> {r.level}
                {r.text ? <span className="muted"> — {r.text}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}
