import { CONDITION_LABEL, type Condition, conditionClass } from "@/lib/derivatives";

/** Flagged conditions (OI expansion/contraction, leverage, funding and basis extremes,
 * liquidation events, stress), each with its threshold and the numbers behind it. */
export function ConditionsPanel({ conditions }: { conditions: Condition[] }) {
  return (
    <section className="status-card" aria-labelledby="deriv-conditions-title">
      <h2 id="deriv-conditions-title">Conditions</h2>
      <p className="muted">
        Calculated flags with published thresholds. They describe positioning; none of them says
        which way price moves.
      </p>
      <table className="status-table">
        <tbody>
          {conditions.map((c) => (
            <tr key={c.condition_id}>
              <th scope="row">{c.label}</th>
              <td>
                <span className={conditionClass(c.state)}>{CONDITION_LABEL[c.state]}</span>
              </td>
              <td className="muted">{c.detail}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
