import type { NavItem } from "@/lib/navigation";

/**
 * Placeholder for a page whose data is not built yet. It deliberately shows no numbers:
 * nothing is displayed until it comes from the database with its evidence category (R2, R3).
 */
export function PagePlaceholder({ item }: { item: NavItem }) {
  return (
    <section className="page">
      <header className="page-header">
        <h1>{item.label}</h1>
        <p className="page-description">{item.description}</p>
      </header>
      <div className="placeholder" role="status">
        <span className="badge badge-neutral">No data sources connected</span>
        <p>
          This page is a placeholder. It will show data only once it comes from the database, with
          its evidence category, timestamp, source, and data quality.
        </p>
        <p className="muted">Planned phase: {item.plannedPhase}</p>
      </div>
    </section>
  );
}
