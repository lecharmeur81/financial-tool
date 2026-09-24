import { MetricFacts } from "@/components/flows/MetricFacts";
import { formatSigned } from "@/lib/institutional";
import { type WhaleScore, whaleBandClass } from "@/lib/whales";

function componentValue(c: WhaleScore["components"][number]): string {
  const v = c.metric.value;
  if (v === null) return "—";
  return c.metric.unit === "ratio"
    ? `${Number(v).toFixed(4)} (ratio)`
    : `${formatSigned(v, 4)} ${c.metric.unit}`;
}

/**
 * The Whale Flow Score with every component (accumulation / distribution metrics): value,
 * reference scale, sub-score, weight and contribution, plus each component's source, timestamp,
 * unit, calculation, freshness and data quality. Excluded components say why.
 */
export function WhaleScoreCard({ score }: { score: WhaleScore }) {
  return (
    <section className="status-card" aria-labelledby="whale-score-title">
      <h2 id="whale-score-title">
        Whale Flow Score · {score.asset} <span className="muted">({score.version})</span>
      </h2>
      <div className="score-head">
        {score.status === "ok" ? (
          <>
            <p className="score-value" aria-label="score value">
              {formatSigned(score.value, 1)}
              <span className="muted"> / ±100</span>
            </p>
            <span className={whaleBandClass(score.band)}>{score.band}</span>
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
        {score.calculation}. Available weight {score.available_weight} of 1.00. Daily windows end on{" "}
        {score.window_end} (UTC). {score.bands_note}
      </p>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Accumulation / distribution metric</th>
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
              <td>{c.reference_scale ?? "—"}</td>
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
      {score.miner_spending ? (
        <p className="muted">
          <strong>{score.miner_spending.label}:</strong> {score.miner_spending.value ?? "—"}
          {score.miner_spending.reason ? ` (${score.miner_spending.reason})` : ""} ·{" "}
          {score.miner_spending.window.start} … {score.miner_spending.window.end} ·{" "}
          {score.miner_spending.calculation}. {score.miner_spending.note}
        </p>
      ) : null}
      <ul className="note-list">
        {score.interpretation_limits.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </section>
  );
}
