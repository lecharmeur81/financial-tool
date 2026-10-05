import Link from "next/link";

import { Unavailable } from "@/components/dashboard/Unavailable";
import {
  DECISION_ASSETS,
  type DecisionAsset,
  type DecisionCurrent,
  fetchDecisionCurrent,
} from "@/lib/decision";
import { type ApiResult, formatUtc } from "@/lib/market";

import { DecisionDisclosure } from "./DecisionDisclosure";
import { EvidencePanels } from "./EvidencePanels";
import { MissingEvidence } from "./MissingEvidence";
import { StanceCard } from "./StanceCard";

function AssetSwitch({ asset }: { asset: DecisionAsset }) {
  return (
    <nav aria-label="Decision Center asset" className="segmented">
      {DECISION_ASSETS.map((a) => (
        <Link
          key={a}
          href={`/?asset=${a}`}
          className={a === asset ? "segment active" : "segment"}
          aria-current={a === asset ? "page" : undefined}
        >
          {a}
        </Link>
      ))}
    </nav>
  );
}

function Frame({ asset, children }: { asset: DecisionAsset; children: React.ReactNode }) {
  return (
    <section className="status-card decision-center" aria-labelledby="decision-center-title">
      <header className="decision-header">
        <div>
          <h2 id="decision-center-title">Decision Center</h2>
          <p className="muted">
            Deterministic, rule-based reading of the latest stored evidence snapshot for {asset}.
            Decision support only — not a prediction and not financial advice.
          </p>
        </div>
        <AssetSwitch asset={asset} />
      </header>
      {children}
    </section>
  );
}

/** The Decision Center for an already-fetched result (pure; the fetching wrapper is below). */
export function DecisionCenterView({
  result,
  asset,
}: {
  result: ApiResult<DecisionCurrent>;
  asset: DecisionAsset;
}) {
  if (!result.ok) {
    if (result.status === 404) {
      return (
        <Frame asset={asset}>
          <div className="decision-callout" role="status">
            <p>
              <strong>No assessment yet.</strong> No stored snapshot is available, so there is
              nothing to assess. Nothing is shown in its place.
            </p>
          </div>
        </Frame>
      );
    }
    return (
      <Frame asset={asset}>
        <Unavailable what="Decision Center" reason={result.reason} />
      </Frame>
    );
  }
  const decision = result.data;
  return (
    <Frame asset={asset}>
      <p className="muted" data-testid="decision-observed">
        Assessment observed {formatUtc(decision.snapshot.as_of)} · snapshot #
        {decision.snapshot.row_id ?? "—"}
      </p>
      {asset !== "BTC" ? (
        <p className="decision-scope-banner" role="note">
          {asset} is not a fully independent analysis: only institutional, whale and derivatives
          evidence is specific to {asset}; the rest is market-wide or BTC-benchmarked.
        </p>
      ) : null}
      <StanceCard decision={decision} />
      <EvidencePanels decision={decision} />
      <MissingEvidence decision={decision} />
      <DecisionDisclosure decision={decision} />
    </Frame>
  );
}

/** Fetches the stored-snapshot decision on its own, independent of every other dashboard fetch. */
export async function DecisionCenterSection({ asset }: { asset: DecisionAsset }) {
  const result = await fetchDecisionCurrent(asset);
  return <DecisionCenterView result={result} asset={asset} />;
}

export function DecisionCenterLoading() {
  return (
    <section className="status-card decision-center" aria-busy="true">
      <h2>Decision Center</h2>
      <p className="muted" role="status">
        Loading the latest assessment…
      </p>
    </section>
  );
}
