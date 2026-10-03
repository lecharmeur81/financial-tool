import type { DivergenceMatrix } from "@/lib/divergence";
import { Unavailable } from "@/components/dashboard/Unavailable";

/**
 * Section 4 — Divergences. Reuses the Divergence Engine's own 10 standardized comparisons
 * unchanged (`/divergence/matrix`) — no divergence logic is calculated in the frontend
 * (Phase 26 constraint). Only divergent pairs are highlighted; the rest are listed for context.
 */
export function DivergenceSection({
  matrix,
}: {
  matrix: { ok: true; data: DivergenceMatrix } | { ok: false; reason: string };
}) {
  if (!matrix.ok) return <Unavailable what="Divergences" reason={matrix.reason} />;
  const divergent = matrix.data.comparisons.filter((c) => c.is_divergent);
  const rest = matrix.data.comparisons.filter((c) => !c.is_divergent);
  return (
    <section className="status-card" aria-labelledby="divergence-title">
      <h2 id="divergence-title">Divergences</h2>
      <p className="muted">
        Observed quadrant between each pair over {matrix.data.window_days} days — never labelled
        bullish or bearish.
      </p>
      {divergent.length ? (
        <table className="status-table">
          <caption>Currently divergent</caption>
          <thead>
            <tr>
              <th scope="col">Comparison</th>
              <th scope="col">Quadrant</th>
              <th scope="col">{"Leg A"}</th>
              <th scope="col">{"Leg B"}</th>
            </tr>
          </thead>
          <tbody>
            {divergent.map((c) => (
              <tr key={c.comparison_id}>
                <th scope="row">{c.title}</th>
                <td>{c.observed_quadrant ?? "—"}</td>
                <td>
                  {c.metric_a.label}: {c.metric_a.direction ?? "—"}
                </td>
                <td>
                  {c.metric_b.label}: {c.metric_b.direction ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="muted">No divergent pairs right now.</p>
      )}
      <details className="component-details">
        <summary>All {matrix.data.comparisons.length} comparisons</summary>
        <ul className="note-list">
          {rest.concat(divergent).map((c) => (
            <li key={c.comparison_id}>
              {c.title}: {c.observed_quadrant ?? "insufficient data"}
              {c.is_divergent ? " (divergent)" : ""}
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}
