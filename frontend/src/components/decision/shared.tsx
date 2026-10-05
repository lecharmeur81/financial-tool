import type { ScopeLabel, TextItem } from "@/lib/decision";

export type Kind = "observed" | "calculated" | "interpretation";

const KIND: Record<Kind, { label: string; title: string }> = {
  observed: { label: "Observed", title: "What the data shows" },
  calculated: { label: "Calculated", title: "What the system calculates from that data" },
  interpretation: { label: "Interpretation", title: "What the evidence means in context" },
};

/** Tags a piece of text with where it comes from, so the three kinds are never blurred. */
export function KindTag({ kind }: { kind: Kind }) {
  return (
    <span className={`kind-tag kind-${kind}`} title={KIND[kind].title}>
      {KIND[kind].label}
    </span>
  );
}

/** Whether evidence is about this asset, or shared market-wide context. */
export function ScopeTag({ label }: { label: ScopeLabel | null }) {
  if (!label) return null;
  return <span className={`scope-tag scope-${label.code}`}>{label.text}</span>;
}

/** An engine sentence, or its id (muted) if the sentence could not be resolved. */
export function EngineText({ item }: { item: TextItem }) {
  return item.text ? <>{item.text}</> : <span className="muted">{item.id}</span>;
}
