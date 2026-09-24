import { classBadge, type Classification, shortAddress } from "@/lib/whales";

/**
 * An address with its classification. The evidence, source, confidence and rule are always one
 * click away; conflicting labels are listed, never hidden.
 */
export function ClassificationCell({ c }: { c: Classification | null }) {
  if (c === null) {
    return <span className="muted">not available (no valid address)</span>;
  }
  return (
    <details className="classification">
      <summary>
        <span className={classBadge(c)}>{c.display}</span> <code>{shortAddress(c.address)}</code>
        {c.conflicting_labels.length ? (
          <>
            {" "}
            <span className="badge badge-warn">conflicting labels</span>
          </>
        ) : null}
      </summary>
      <dl className="facts compact">
        <div>
          <dt>Address</dt>
          <dd>
            <code>{c.address}</code>
          </dd>
        </div>
        <div>
          <dt>Evidence</dt>
          <dd>
            {c.evidence}
            {c.evidence_class ? (
              <span className="badge badge-neutral">{c.evidence_class} evidence</span>
            ) : null}
          </dd>
        </div>
        <div>
          <dt>Source</dt>
          <dd>
            {c.source_url ? (
              <a href={c.source_url} target="_blank" rel="noopener noreferrer">
                {c.source}
              </a>
            ) : (
              (c.source ?? "—")
            )}{" "}
            <span className="muted">({c.rule})</span>
          </dd>
        </div>
        <div>
          <dt>Confidence</dt>
          <dd>{c.confidence ?? "—"}</dd>
        </div>
        {c.conflicting_labels.length ? (
          <div>
            <dt>Conflicts</dt>
            <dd>
              <ul className="note-list">
                {c.conflicting_labels.map((x) => (
                  <li key={`${x.source}-${x.actor_class}-${x.entity_id ?? ""}`}>
                    {x.actor_class} {x.entity_id ?? ""} · {x.evidence_class} · {x.confidence} ·{" "}
                    {x.source}
                  </li>
                ))}
              </ul>
            </dd>
          </div>
        ) : null}
      </dl>
    </details>
  );
}
