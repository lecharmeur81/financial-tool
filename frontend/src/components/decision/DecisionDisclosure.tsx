import {
  DIRECTION_LABEL,
  type DecisionCurrent,
  domainLabel,
  evidenceStateLabel,
} from "@/lib/decision";
import { formatUtc } from "@/lib/market";

import { KindTag, ScopeTag } from "./shared";

function list(items: string[]) {
  return items.length ? items.join(", ") : "none";
}

/** Everything technical, collapsed by default (progressive disclosure). */
export function DecisionDisclosure({ decision }: { decision: DecisionCurrent }) {
  const { snapshot, methodology, data_quality: dq, technical } = decision;
  return (
    <details className="component-details decision-disclosure">
      <summary>Technical details, data quality and methodology</summary>

      <h4>How to read this</h4>
      <ul className="note-list">
        <li>
          <KindTag kind="observed" /> What the data shows: values and notes recorded in the stored
          snapshot.
        </li>
        <li>
          <KindTag kind="calculated" /> What the system calculates from that data: scores, bands and
          the stance, confidence and posture rules.
        </li>
        <li>
          <KindTag kind="interpretation" /> What the evidence means in context: the engine&apos;s
          fixed explanatory sentences. No AI model writes any of this text.
        </li>
      </ul>

      <h4>Evidence by area</h4>
      <div className="table-scroll">
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Area</th>
              <th scope="col">Scope</th>
              <th scope="col">Availability</th>
              <th scope="col">Reading</th>
            </tr>
          </thead>
          <tbody>
            {decision.domains.map((d) => (
              <tr key={d.component}>
                <td>{domainLabel(d.domain)}</td>
                <td>
                  <ScopeTag label={d.scope_label} />
                </td>
                <td>{evidenceStateLabel(d.evidence_state)}</td>
                <td>
                  {d.direction ? (DIRECTION_LABEL[d.direction] ?? d.direction) : "—"}
                  {d.band ? ` · ${d.band}` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h4>Data quality</h4>
      <p className="muted">
        Taken from the assessment&apos;s own reading statuses, not from the snapshot producer&apos;s
        summary flag.
      </p>
      <dl className="facts compact">
        <dt>Unavailable</dt>
        <dd>{list(dq.unavailable_components)}</dd>
        <dt>Stale</dt>
        <dd>{list(dq.stale_components)}</dd>
        <dt>Partial</dt>
        <dd>{list(dq.partial_components)}</dd>
        <dt>Freshness not assessed</dt>
        <dd>{list(dq.not_assessed_components)}</dd>
        <dt>Tools reported unavailable / degraded</dt>
        <dd>
          {list(dq.unavailable_tools)} / {list(dq.degraded_tools)}
        </dd>
        <dt>Data later than the snapshot&apos;s knowledge time</dt>
        <dd>{list(dq.look_ahead_violations)}</dd>
      </dl>
      {dq.platform_limits.length > 0 ? (
        <>
          <p className="muted">Declared platform limits:</p>
          <ul className="note-list">
            {dq.platform_limits.map((limit) => (
              <li key={limit}>{limit}</li>
            ))}
          </ul>
        </>
      ) : null}

      <h4>Snapshot</h4>
      <dl className="facts compact">
        <dt>Observed at</dt>
        <dd>{formatUtc(snapshot.as_of)}</dd>
        <dt>Knowledge time</dt>
        <dd>{formatUtc(snapshot.knowledge_time)}</dd>
        <dt>Stored at</dt>
        <dd>{formatUtc(snapshot.row_created_at)}</dd>
        <dt>Snapshot</dt>
        <dd>
          #{snapshot.row_id ?? "—"} · {snapshot.uuid ?? "—"} · {snapshot.snapshot_version}
        </dd>
        <dt>Stored payload hash</dt>
        <dd className="mono">
          {snapshot.producer_payload_hash ?? "—"} ({snapshot.producer_hash_check})
        </dd>
        <dt>Decision input hash</dt>
        <dd className="mono">{snapshot.decision_input_hash}</dd>
      </dl>

      <h4>Methodology</h4>
      <dl className="facts compact">
        <dt>Methodology / parameters / templates</dt>
        <dd>
          {methodology.methodology_version} · {methodology.parameter_version} ·{" "}
          {methodology.template_version}
        </dd>
        <dt>Posture rule</dt>
        <dd>{methodology.posture_rule_id}</dd>
        <dt>Confidence rules</dt>
        <dd>{list(methodology.confidence_rule_ids)}</dd>
        <dt>Rules that fired</dt>
        <dd>{list(methodology.fired_rule_ids)}</dd>
      </dl>

      <h4>Observed values behind the evidence</h4>
      {technical.fields.length === 0 ? (
        <p className="muted">No displayable values were recorded for this assessment.</p>
      ) : (
        <div className="table-scroll">
          <table className="status-table">
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Value</th>
                <th scope="col">Source</th>
              </tr>
            </thead>
            <tbody>
              {technical.fields.map((f) => (
                <tr key={f.field_id}>
                  <td className="mono">{f.field_id}</td>
                  <td>
                    {f.display}
                    {f.unit ? ` ${f.unit}` : ""}
                  </td>
                  <td>{f.source ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {technical.fields_without_display > 0 ? (
        <p className="muted">
          {technical.fields_without_display} cited field(s) have no recorded value and are not
          treated as evidence.
        </p>
      ) : null}
    </details>
  );
}
