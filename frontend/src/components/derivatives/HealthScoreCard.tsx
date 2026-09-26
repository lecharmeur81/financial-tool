import { type HealthScore, stressBandClass } from "@/lib/derivatives";

/**
 * The Derivatives Health Score with every component: metric value, reference scale,
 * direction-neutral stress (0 … 1), weight and contribution to stress, the calculation, and the
 * direction shown as context (never scored). Excluded components say why.
 */
export function HealthScoreCard({ score, asset }: { score: HealthScore; asset: string }) {
  return (
    <section className="status-card" aria-labelledby="deriv-score-title">
      <h2 id="deriv-score-title">
        Derivatives Health Score · {asset} <span className="muted">({score.version})</span>
      </h2>
      <div className="score-head">
        {score.status === "ok" ? (
          <>
            <p className="score-value" aria-label="health score">
              {Number(score.health).toFixed(1)}
              <span className="muted"> / 100</span>
            </p>
            <span className={stressBandClass(score.band)}>{score.band}</span>
            <span className="muted">stress {Number(score.stress).toFixed(1)}</span>
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
        100 = no sign of stress; stress = 100 − health. Available weight {score.available_weight} of
        1.00. {score.band_note}
      </p>
      <p className="muted">{score.semantic_note}</p>
      <p className="muted">
        Calculated {new Date(score.calculated_at).toLocaleString()} from parameters version{" "}
        {score.version}.
      </p>
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Component</th>
            <th scope="col">Value</th>
            <th scope="col">Reference scale</th>
            <th scope="col">Stress (0–1)</th>
            <th scope="col">Weight (effective)</th>
            <th scope="col">Contribution</th>
            <th scope="col">Context (not scored)</th>
          </tr>
        </thead>
        <tbody>
          {score.components.map((c) => (
            <tr key={c.component_id}>
              <th scope="row">
                {c.label}
                {c.status !== "ok" ? (
                  <>
                    {" "}
                    <span className="badge badge-warn">
                      {c.status === "not_applicable" ? "not applicable" : "excluded"}
                    </span>
                  </>
                ) : null}
              </th>
              <td>{c.value === null ? "—" : `${c.value} ${c.value_unit}`}</td>
              <td>{c.scale}</td>
              <td>{c.stress ?? "—"}</td>
              <td>
                {c.weight}
                {c.effective_weight ? ` (${c.effective_weight})` : ""}
              </td>
              <td>{c.contribution === null ? "—" : `${c.contribution} pts`}</td>
              <td>{c.context ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {score.components.map((c) => (
        <details key={c.component_id} className="component-details">
          <summary>
            {c.label} — definition and calculation{c.reason ? ` · ${c.reason}` : ""}
          </summary>
          <p className="muted">
            {c.definition} Metric id: {c.metric_id}.
          </p>
          {c.calculation ? <p>{c.calculation}</p> : null}
          {Object.keys(c.inputs).length ? (
            <ul className="note-list">
              {Object.entries(c.inputs).map(([k, v]) => (
                <li key={k}>
                  {k}: {v ?? "—"}
                </li>
              ))}
            </ul>
          ) : null}
        </details>
      ))}
    </section>
  );
}
