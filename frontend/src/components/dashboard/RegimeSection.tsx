import type { RegimeCurrent } from "@/lib/regime";
import { formatUtc } from "@/lib/market";

/**
 * Section 1 — Market Regime. Confidence is confidence in the classification itself, never a
 * probability of price direction (Phase 26 explicit requirement) — `confidence_semantic_note`
 * carries the backend's own wording verbatim so that distinction is never lost in translation.
 */
export function RegimeSection({ regime }: { regime: RegimeCurrent }) {
  if (regime.status !== "ok") {
    return (
      <section className="status-card" aria-labelledby="regime-title">
        <h2 id="regime-title">Market Regime</h2>
        <p className="muted">Insufficient data. {regime.reason ?? ""}</p>
      </section>
    );
  }
  return (
    <section className="status-card" aria-labelledby="regime-title">
      <h2 id="regime-title">Market Regime · {regime.asset}</h2>
      <div className="score-head">
        <p className="score-value">{regime.label ?? "—"}</p>
        {regime.held_by_hysteresis ? (
          <span className="badge badge-neutral">held (hysteresis)</span>
        ) : null}
      </div>
      <p>
        Confidence in this classification: <strong>{regime.confidence ?? "—"}</strong>
        {" — "}
        <span className="muted">{regime.confidence_semantic_note}</span>
      </p>
      <p className="muted">
        In this regime since {regime.regime_start_date ?? "—"} ({regime.regime_duration_days} day
        {regime.regime_duration_days === 1 ? "" : "s"}
        {regime.regime_duration_capped ? ", capped at the start of stored history" : ""}).
      </p>
      {regime.contributing_metrics.length ? (
        <details className="component-details" open>
          <summary>Key supporting evidence ({regime.contributing_metrics.length})</summary>
          <ul className="note-list">
            {regime.contributing_metrics.map((m) => (
              <li key={m.condition_id}>
                {m.label}: {m.value ?? "—"} — {m.rationale}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
      {regime.contradicting_metrics.length ? (
        <details className="component-details">
          <summary>
            Important uncertainty — contradicting metrics ({regime.contradicting_metrics.length})
          </summary>
          <ul className="note-list">
            {regime.contradicting_metrics.map((m) => (
              <li key={m.condition_id}>
                {m.label}: {m.value ?? "—"} — {m.rationale}
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <p className="muted">No contradicting metrics recorded for this regime right now.</p>
      )}
      <p className="muted">Classified as of {formatUtc(regime.as_of)}.</p>
    </section>
  );
}
