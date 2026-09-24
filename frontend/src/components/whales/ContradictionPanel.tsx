import { formatSigned } from "@/lib/institutional";
import { CONTRADICTION_LABEL, contradictionClass, type Contradiction } from "@/lib/whales";

function formatReading(r: Contradiction["readings"][number]): string {
  if (r.value === null) return "—";
  if (r.unit === "score") return `${formatSigned(r.value, 1)} points`;
  if (r.unit === "%") return formatSigned(r.value, 2, " %");
  return `${formatSigned(r.value, 4)} ${r.unit}`;
}

/** Where readings from different sources point in different directions — shown, never averaged. */
export function ContradictionPanel({
  items,
  rule,
}: {
  items: Contradiction[];
  rule: string | null;
}) {
  return (
    <section className="status-card" aria-labelledby="contradictions-title">
      <h2 id="contradictions-title">Contradiction indicators</h2>
      {rule ? <p className="muted">{rule}</p> : null}
      <table className="status-table">
        <thead>
          <tr>
            <th scope="col">Indicator</th>
            <th scope="col">Status</th>
            <th scope="col">Readings</th>
            <th scope="col">Explanation</th>
          </tr>
        </thead>
        <tbody>
          {items.map((x) => (
            <tr key={x.indicator_id}>
              <th scope="row">{x.label}</th>
              <td>
                <span className={contradictionClass(x.status)}>
                  {CONTRADICTION_LABEL[x.status]}
                </span>
              </td>
              <td>
                <ul className="note-list">
                  {x.readings.map((r) => (
                    <li key={r.label}>
                      {r.label}: {formatReading(r)} → {r.direction}{" "}
                      <span className="muted">({r.source})</span>
                    </li>
                  ))}
                </ul>
              </td>
              <td>{x.explanation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
