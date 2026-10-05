import {
  type DecisionCurrent,
  type DomainReading,
  REASON_KIND_LABEL,
  domainLabel,
  evidenceStateLabel,
  isAvailableState,
} from "@/lib/decision";

import { EngineText, KindTag, ScopeTag } from "./shared";

function freshnessLine(reading: DomainReading): string | null {
  const info = reading.freshness_info;
  const counts = Object.entries(info.status_counts);
  const parts: string[] = [];
  if (info.expected_latest || info.latest) {
    parts.push(
      `latest data: ${info.latest ?? "none"}${info.expected_latest ? `; expected by ${info.expected_latest}` : ""}`,
    );
  }
  if (counts.length > 0) {
    parts.push(
      `source freshness: ${counts.map(([status, n]) => `${status.replace(/_/g, " ")} (${n})`).join(", ")}`,
    );
  }
  return parts.length ? parts.join(" · ") : null;
}

/**
 * What is missing or weak, with the snapshot's own explicit reason strings. A cause is only ever
 * stated when the stored snapshot records it: when it records none, this says so. Nothing here
 * claims a missing key, a provider outage, a failed ingestion or a disconnected source.
 */
export function MissingEvidence({ decision }: { decision: DecisionCurrent }) {
  const weak = decision.domains
    .filter((d) => !isAvailableState(d.evidence_state) || d.quality_flags.length > 0)
    .sort((a, b) => Number(b.role === "Directional") - Number(a.role === "Directional"));

  return (
    <section aria-labelledby="decision-missing-title">
      <h3 id="decision-missing-title">What is missing, and what limits confidence</h3>
      {weak.length === 0 ? (
        <p className="muted">No evidence area is reported as missing or weak.</p>
      ) : (
        <ul className="decision-missing">
          {weak.map((d) => {
            const fresh = freshnessLine(d);
            return (
              <li key={d.component}>
                <div>
                  <strong>{domainLabel(d.domain)}</strong> <ScopeTag label={d.scope_label} />{" "}
                  <span className="badge badge-neutral">
                    {evidenceStateLabel(d.evidence_state)}
                  </span>
                  {d.quality_flags.length > 0 ? (
                    <span className="badge badge-warn">{d.quality_flags.join(", ")}</span>
                  ) : null}
                </div>
                {d.reasons.length > 0 ? (
                  <ul className="note-list">
                    {d.reasons.map((r) => (
                      <li key={r.path}>
                        <KindTag kind="observed" /> <em>{REASON_KIND_LABEL[r.kind] ?? r.kind}:</em>{" "}
                        {r.text}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="muted">The stored snapshot records no reason for this.</p>
                )}
                {fresh ? <p className="muted">{fresh}</p> : null}
              </li>
            );
          })}
        </ul>
      )}

      {decision.why.missing_context.length > 0 ? (
        <ul className="note-list">
          {decision.why.missing_context.map((item) => (
            <li key={item.id}>
              <KindTag kind="interpretation" /> <EngineText item={item} />
            </li>
          ))}
        </ul>
      ) : null}

      {decision.scope_notes.length > 0 ? (
        <ul className="note-list decision-scope-notes">
          {decision.scope_notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}

      {decision.limitations.length > 0 ? (
        <>
          <h4>Current limitations</h4>
          <ul className="note-list">
            {decision.limitations.map((item) => (
              <li key={item.id}>
                <KindTag kind="interpretation" /> <EngineText item={item} />
              </li>
            ))}
          </ul>
        </>
      ) : null}

      <p className="muted">
        Formal confirmation, weakening and invalidation conditions are a future capability and are
        not part of this assessment; only the missing evidence, conflicts and limits above are
        shown.
      </p>
    </section>
  );
}
