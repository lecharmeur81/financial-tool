import { bandClass, formatSigned, type Score } from "@/lib/institutional";

import { MetricFacts } from "./MetricFacts";

function componentValue(c: Score["components"][number]): string {
  const v = c.metric.value;
  if (v === null) return "—";
  return c.metric.unit.startsWith("%")
    ? `${formatSigned(v, 3)} ${c.metric.unit}`
    : `${formatSigned(v, 3)} (${c.metric.unit})`;
}

/**
 * The Institutional Flow Score with every component, its weight, sub-score and contribution.
 * Nothing is hidden: unavailable components say why, and every component shows its own source,
 * timestamp, unit, calculation, freshness and data quality.
 */
export function ScoreCard({ score }: { score: Score }) {
  return (
    <section className="status-card" aria-labelledby="score-title">
      <h2 id="score-title">
        Institutional Flow Score · {score.asset} <span className="muted">({score.version})</span>
      </h2>
      <div className="score-head">
        {score.status === "ok" ? (
          <>
            <p className="score-value" aria-label="score value">
              {formatSigned(score.value, 1)}
              <span className="muted"> / ±100</span>
            </p>
            <span className={bandClass(score.band)}>{score.band}</span>
          </>
        ) : (
          <p className="score-value" role="status">
            Insufficient data
          </p>
        )}
        <span className="badge badge-neutral">Calculated metric</span>
      </div>
      {score.reason ? <p className="muted">{score.reason}</p> : null}
      <p className="muted">
        {score.calculation}. Available weight {score.available_weight} of 1.00. ETF windows end at
        the latest trading day due: {score.etf_due_until}. {score.bands_note}
      </p>

      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Component</th>
            <th scope="col">Value</th>
            <th scope="col">Reference scale</th>
            <th scope="col">Sub-score</th>
            <th scope="col">Weight (effective)</th>
            <th scope="col">Contribution</th>
          </tr>
        </thead>
        <tbody>
          {score.components.map((c) => (
            <tr key={c.component_id}>
              <th scope="row">
                {c.metric.label}
                {c.status === "unavailable" ? (
                  <>
                    {" "}
                    <span className="badge badge-warn">excluded</span>
                  </>
                ) : null}
              </th>
              <td>{componentValue(c)}</td>
              <td>{c.reference_scale ?? "none (already −1 … +1)"}</td>
              <td>{formatSigned(c.sub_score, 4)}</td>
              <td>
                {c.weight}
                {c.effective_weight ? ` (${c.effective_weight})` : ""}
              </td>
              <td>{c.contribution === null ? "—" : `${formatSigned(c.contribution, 2)} pts`}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {score.components.map((c) => (
        <details key={c.component_id} className="component-details">
          <summary>
            {c.metric.label} — source, calculation, freshness, quality
            {c.reason ? ` · ${c.reason}` : ""}
          </summary>
          <p className="muted">
            Definition: {c.definition} Window: {c.window.start ?? "—"} … {c.window.end ?? "—"}.{" "}
            {c.evidence}.
          </p>
          <MetricFacts metric={c.metric} />
        </details>
      ))}

      <ul className="note-list">
        {score.interpretation_limits.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </section>
  );
}
