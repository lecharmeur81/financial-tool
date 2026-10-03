import type { RotationMatrix } from "@/lib/rotation";
import { Unavailable } from "@/components/dashboard/Unavailable";

/**
 * Section 6 — Capital Rotation (Phase 20). Every pair keeps OBSERVED market-share movement
 * (each node's own reading) strictly separate from INFERRED capital rotation (a hedged
 * hypothesis) and from the OBSERVED flow evidence that corroborates or contradicts it.
 * Inferred rotation is never displayed as confirmed capital movement (Phase 26 constraint).
 */
export function RotationSection({
  matrix,
}: {
  matrix: { ok: true; data: RotationMatrix } | { ok: false; reason: string };
}) {
  if (!matrix.ok) return <Unavailable what="Capital rotation" reason={matrix.reason} />;
  const withHypothesis = matrix.data.pairs.filter(
    (p) => p.inferred_capital_rotation.status === "possible_rotation",
  );
  return (
    <section className="status-card" id="rotation" aria-labelledby="rotation-title">
      <h2 id="rotation-title">Capital Rotation</h2>
      <p className="muted">{matrix.data.evidence_note}</p>
      {withHypothesis.length ? (
        withHypothesis.map((p) => (
          <details
            key={`${p.from_node.node_id}-${p.to_node.node_id}`}
            className="component-details"
          >
            <summary>
              {p.from_node.label} ({p.observed_capital_flow.from_node_direction ?? "—"}) ↔{" "}
              {p.to_node.label} ({p.observed_capital_flow.to_node_direction ?? "—"})
            </summary>
            <p>
              <span className="badge badge-neutral">Inferred — not confirmed</span>{" "}
              {p.inferred_capital_rotation.hypothesis ?? "—"}
            </p>
            {p.flow_corroboration.supporting_evidence.length ? (
              <>
                <p className="muted">Supporting observed flow evidence:</p>
                <ul className="note-list">
                  {p.flow_corroboration.supporting_evidence.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </>
            ) : null}
            {p.flow_corroboration.contradicting_evidence.length ? (
              <>
                <p className="muted">Contradicting observed flow evidence:</p>
                <ul className="note-list">
                  {p.flow_corroboration.contradicting_evidence.map((s) => (
                    <li key={s}>{s}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </details>
        ))
      ) : (
        <p className="muted">
          No node pair currently diverges enough to suggest possible rotation.
        </p>
      )}
    </section>
  );
}
