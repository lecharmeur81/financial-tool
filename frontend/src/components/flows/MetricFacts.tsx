import { type FreshnessInfo, type Metric, type Quality, type Source } from "@/lib/institutional";
import { FRESHNESS_CLASS, FRESHNESS_LABEL, formatAge, formatUtc } from "@/lib/market";

const EVIDENCE_LABEL: Record<string, string> = {
  observed: "Observed data",
  metric: "Calculated metric",
};

export function SourceText({ source }: { source: Source }) {
  return (
    <>
      {source.provider_name} · dataset <code>{source.dataset_id}</code>
      {source.attribution ? (
        <>
          {" "}
          ·{" "}
          <a href={source.attribution.url} target="_blank" rel="noopener noreferrer">
            {source.attribution.text}
          </a>
        </>
      ) : null}
      {source.enabled ? "" : " · ingestion disabled in settings"}
    </>
  );
}

export function FreshnessText({ freshness }: { freshness: FreshnessInfo }) {
  return (
    <>
      <span className={FRESHNESS_CLASS[freshness.status]}>{FRESHNESS_LABEL[freshness.status]}</span>{" "}
      {freshness.note}
      {freshness.expected_latest ? ` · latest day due: ${freshness.expected_latest}` : ""}
      {freshness.age_seconds !== null ? ` · ${formatAge(freshness.age_seconds)}` : ""}
      <span className="muted"> ({freshness.rule})</span>
    </>
  );
}

export function QualityText({ quality }: { quality: Quality }) {
  const counts =
    quality.days_expected !== null && quality.days_present !== null
      ? `${quality.days_present} of ${quality.days_expected} days with data`
      : null;
  return (
    <>
      <span className={quality.status === "ok" ? "badge badge-ok" : "badge badge-warn"}>
        {quality.status}
      </span>
      {counts ? ` ${counts}` : ""}
      {quality.notes.length ? (
        <ul className="note-list">
          {quality.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

/**
 * The six things every metric must show (Phase 6): source, timestamp, unit, calculation,
 * freshness and data quality — plus its evidence category and evidence class.
 */
export function MetricFacts({ metric }: { metric: Metric }) {
  const timestamp =
    metric.timestamp && metric.timestamp.length > 10
      ? formatUtc(metric.timestamp)
      : (metric.timestamp ?? "—");
  return (
    <dl className="facts compact">
      <div>
        <dt>Evidence</dt>
        <dd>
          <span className="badge badge-neutral">
            {EVIDENCE_LABEL[metric.evidence_category] ?? metric.evidence_category}
          </span>
          {metric.evidence_class ? (
            <span className="badge badge-neutral">{metric.evidence_class} evidence</span>
          ) : null}
        </dd>
      </div>
      <div>
        <dt>Source</dt>
        <dd>
          <SourceText source={metric.source} />
        </dd>
      </div>
      <div>
        <dt>Timestamp</dt>
        <dd>{timestamp}</dd>
      </div>
      <div>
        <dt>Unit</dt>
        <dd>{metric.unit}</dd>
      </div>
      <div>
        <dt>Calculation</dt>
        <dd>{metric.calculation}</dd>
      </div>
      <div>
        <dt>Freshness</dt>
        <dd>
          <FreshnessText freshness={metric.freshness} />
        </dd>
      </div>
      <div>
        <dt>Data quality</dt>
        <dd>
          <QualityText quality={metric.quality} />
        </dd>
      </div>
    </dl>
  );
}
