import type { SimilarityCurrent } from "@/lib/similarity";
import { Unavailable } from "@/components/dashboard/Unavailable";

/**
 * Historical Similarity (Phase 15, surfaced on /analytics in Phase 36). Reuses the Similarity
 * Engine's own analogue search unchanged (`/similarity/current`) — no new scoring or matching
 * logic in the frontend. Historical context only, never a prediction: every analogue's forward
 * return and drawdown are what actually happened after that date, not a forecast for today.
 */
export function SimilaritySection({
  similarity,
}: {
  similarity: { ok: true; data: SimilarityCurrent } | { ok: false; reason: string };
}) {
  if (!similarity.ok)
    return <Unavailable what="Historical similarity" reason={similarity.reason} />;
  const data = similarity.data;

  if (data.status !== "ok") {
    return (
      <section className="status-card" aria-labelledby="similarity-title">
        <h2 id="similarity-title">Historical Similarity</h2>
        <p className="muted">Insufficient data. {data.reason ?? ""}</p>
      </section>
    );
  }

  return (
    <section className="status-card" aria-labelledby="similarity-title">
      <h2 id="similarity-title">Historical Similarity · {data.asset}</h2>
      <p className="muted">Historical context only — not a prediction. {data.evidence_note}</p>
      {data.analogues.length ? (
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Date</th>
              <th scope="col">Similarity</th>
              <th scope="col">Regime then</th>
              <th scope="col">7d forward</th>
              <th scope="col">30d forward</th>
              <th scope="col">Max drawdown</th>
            </tr>
          </thead>
          <tbody>
            {data.analogues.map((a) => {
              const fwd7 = a.forward_returns.find((r) => r.horizon_days === 7);
              const fwd30 = a.forward_returns.find((r) => r.horizon_days === 30);
              return (
                <tr key={a.date}>
                  <th scope="row">{a.date ?? "—"}</th>
                  <td>{a.similarity_score ?? "—"}</td>
                  <td>{a.regime.label ?? "—"}</td>
                  <td>
                    {fwd7?.status === "ok" && fwd7.value_pct !== null
                      ? `${fwd7.value_pct}%`
                      : (fwd7?.reason ?? "not yet knowable")}
                  </td>
                  <td>
                    {fwd30?.status === "ok" && fwd30.value_pct !== null
                      ? `${fwd30.value_pct}%`
                      : (fwd30?.reason ?? "not yet knowable")}
                  </td>
                  <td>
                    {a.max_drawdown.status === "ok" && a.max_drawdown.value_pct !== null
                      ? `${a.max_drawdown.value_pct}%${a.max_drawdown.partial ? " (partial)" : ""}`
                      : (a.max_drawdown.reason ?? "—")}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : (
        <p className="muted">No historical analogues found.</p>
      )}

      {data.distribution.length ? (
        <details className="component-details">
          <summary>Forward-return distribution across sampled analogues</summary>
          <table className="status-table">
            <thead>
              <tr>
                <th scope="col">Horizon</th>
                <th scope="col">Sample</th>
                <th scope="col">Min</th>
                <th scope="col">p25</th>
                <th scope="col">Median</th>
                <th scope="col">p75</th>
                <th scope="col">Max</th>
              </tr>
            </thead>
            <tbody>
              {data.distribution.map((d) => (
                <tr key={d.horizon_days}>
                  <th scope="row">{d.horizon_days}d</th>
                  {d.status === "ok" ? (
                    <>
                      <td>{d.count}</td>
                      <td>{d.min_pct ?? "—"}%</td>
                      <td>{d.p25_pct ?? "—"}%</td>
                      <td>{d.median_pct ?? "—"}%</td>
                      <td>{d.p75_pct ?? "—"}%</td>
                      <td>{d.max_pct ?? "—"}%</td>
                    </>
                  ) : (
                    <td colSpan={6} className="muted">
                      {d.reason ?? "Insufficient data."}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      ) : null}
    </section>
  );
}
