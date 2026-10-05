import { type DecisionCurrent, INSUFFICIENT_STANCE, domainLabel } from "@/lib/decision";

import { EngineText, KindTag } from "./shared";

/**
 * Stance, evidence confidence and posture — the engine's own labels, unchanged — with a
 * plain-English reading. Confidence is never turned into a probability, and CAP-U is explained
 * from the engine's result, never recalculated here.
 */
export function StanceCard({ decision }: { decision: DecisionCurrent }) {
  const { stance, cap_u: capU, coverage, why } = decision;
  const insufficient = stance.final === INSUFFICIENT_STANCE;
  const missingIds = new Set(why.missing_context.map((i) => i.id));
  const reasons = [
    ...why.directional.filter((i) => !i.id.startsWith("STANCE.") && !missingIds.has(i.id)),
    ...why.limits,
  ];

  return (
    <div className="decision-stance">
      <dl className="decision-tiles">
        <div className="decision-tile">
          <dt>Market stance</dt>
          <dd className="decision-value" data-testid="decision-stance">
            {stance.final}
          </dd>
        </div>
        <div className="decision-tile">
          <dt>Evidence confidence</dt>
          <dd className="decision-value" data-testid="decision-confidence">
            {stance.confidence}
          </dd>
        </div>
        <div className="decision-tile">
          <dt>Posture</dt>
          <dd className="decision-value" data-testid="decision-posture">
            {stance.posture}
          </dd>
        </div>
      </dl>

      {insufficient ? (
        <div className="decision-callout" role="note">
          <p>
            <strong>This is a valid result, not an error.</strong> The system does not currently
            have enough reliable evidence to take a bullish or bearish stance.
          </p>
          <p>
            {coverage.available} of {coverage.expected} core evidence areas currently have usable
            data for {decision.asset}.
          </p>
        </div>
      ) : stance.headline ? (
        <p className="decision-headline">
          <KindTag kind="interpretation" /> {stance.headline}
        </p>
      ) : null}

      {stance.cap_u_applied ? (
        <div className="decision-cap" role="note" data-testid="decision-cap-u">
          <h3>Why the final stance is more cautious than the evidence</h3>
          {stance.differs_from_raw ? (
            <p>
              The underlying evidence reads <strong>{stance.raw}</strong>, but the final stance is{" "}
              <strong>{stance.final}</strong> (posture: {stance.posture}) because required evidence
              could not be evaluated.
            </p>
          ) : (
            <p>
              Required evidence could not be evaluated, but it did not change the stance (
              <strong>{stance.final}</strong>).
            </p>
          )}
          <ul className="note-list">
            {capU.map((c) => (
              <li key={`${c.rule_id}-${c.source_field_id}`}>
                {domainLabel(c.cap_source)} could not be evaluated
                {c.binding ? " — this limits the stance" : ""}.{" "}
                {c.text ? <span>{c.text} </span> : null}
                <span className="muted">
                  ({c.rule_id}; stance before limits: {c.raw_stance})
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {reasons.length > 0 ? (
        <div className="decision-why">
          <h3>Why?</h3>
          <ul className="note-list">
            {reasons.map((item) => (
              <li key={item.id}>
                <KindTag kind="interpretation" /> <EngineText item={item} />
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="muted">
        Evidence confidence describes how complete and consistent the evidence is. It is not a
        probability of any price move. This is decision support, not financial advice.
      </p>
    </div>
  );
}
