import Link from "next/link";

import { Unavailable } from "@/components/dashboard/Unavailable";
import { ADVISOR_ASSETS } from "@/lib/advisor";
import { type ApiResult, formatDecimal } from "@/lib/market";
import {
  type ExposureAsset,
  type PortfolioExposure,
  fetchPortfolioExposure,
  formatShare,
  invalidReasonLabel,
  priceStatusLabel,
  relationLabel,
} from "@/lib/portfolio";

const usd = (value: string): string => `${formatDecimal(value, 2)} USD`;

const advisorHref = (asset: string): string =>
  (ADVISOR_ASSETS as readonly string[]).includes(asset) ? `/advisor?asset=${asset}` : "/advisor";

function Frame({ children }: { children: React.ReactNode }) {
  return (
    <section className="status-card decision-center" aria-labelledby="exposure-title">
      <header className="decision-header">
        <div>
          <h2 id="exposure-title">Paper Portfolio Exposure</h2>
          <p className="muted">
            A descriptive summary of your open simulated paper trades, compared with the Advisor
            Brief. General context only — not a prediction, not personalized advice, and no trade is
            placed.
          </p>
        </div>
        <nav aria-label="Related views" className="related-links">
          <Link href="/advisor">Advisor Brief</Link>
          <Link href="/paper">Paper Trading</Link>
          <Link href="/">Dashboard</Link>
        </nav>
      </header>
      <p className="decision-scope-banner" role="note" data-testid="exposure-simulated-banner">
        <strong>Simulated paper trades only.</strong> These are hypothetical positions logged for
        practice — not real holdings, balances or exchange positions.
      </p>
      {children}
    </section>
  );
}

function errorPanel(result: Extract<ApiResult<PortfolioExposure>, { ok: false }>) {
  if (result.status === 503) {
    return (
      <div role="alert" data-testid="exposure-error-503">
        <Unavailable
          what="Paper portfolio exposure"
          reason={`The paper trades cannot be read right now. ${result.reason}`}
        />
      </div>
    );
  }
  return (
    <div data-testid="exposure-error-other">
      <Unavailable
        what="Paper portfolio exposure"
        reason={result.status === null ? result.reason : `${result.reason} (HTTP ${result.status})`}
      />
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="decision-tile">
      <dt>{label}</dt>
      <dd className="decision-value">{value}</dd>
      {note ? <dd className="muted">{note}</dd> : null}
    </div>
  );
}

function Summary({ data }: { data: PortfolioExposure }) {
  const s = data.summary;
  return (
    <section aria-labelledby="exposure-summary-title" data-testid="exposure-summary">
      <h3 id="exposure-summary-title">Calculated from the simulated trades</h3>
      <p className="muted">
        Sizes are the simulated notional fixed at entry, in USD. They are not marked to market.
      </p>
      <dl className="decision-tiles">
        <Tile label="Gross notional" value={usd(s.gross_notional)} />
        <Tile label="Long notional" value={usd(s.long_notional)} />
        <Tile label="Short notional" value={usd(s.short_notional)} />
        <Tile label="Net notional (long − short)" value={usd(s.net_notional)} />
        <Tile label="Total margin" value={usd(s.total_margin)} />
        <Tile
          label="Notional-weighted leverage"
          value={
            s.notional_weighted_leverage === null
              ? "—"
              : `${formatDecimal(s.notional_weighted_leverage, 2)}×`
          }
        />
        <Tile
          label="Largest asset share"
          value={s.largest_asset ? `${s.largest_asset} ${formatShare(s.largest_asset_share)}` : "—"}
        />
        <Tile
          label="Concentration (sum of squared shares)"
          value={s.concentration_hhi === null ? "—" : formatDecimal(s.concentration_hhi, 4)}
          note="Descriptive only: no threshold, no verdict."
        />
      </dl>
    </section>
  );
}

function BriefCell({ asset }: { asset: ExposureAsset }) {
  const brief = asset.brief;
  if (brief.status === "not_assessed") {
    return (
      <>
        <span className="badge badge-warn">Not assessed</span>{" "}
        <span className="muted">{brief.reason}</span>
      </>
    );
  }
  return (
    <>
      <strong>{brief.stance}</strong>{" "}
      <span className="muted">
        {brief.confidence} confidence · {brief.decision_state.replace(/_/g, " ")}
      </span>
    </>
  );
}

function Assets({ data }: { data: PortfolioExposure }) {
  return (
    <section aria-labelledby="exposure-assets-title" data-testid="exposure-assets">
      <h3 id="exposure-assets-title">By asset, compared with the Advisor Brief</h3>
      <p className="muted">
        The comparison is descriptive, not an instruction. A missing brief is shown as not assessed,
        never as neutral or agreeing.
      </p>
      <div className="table-scroll">
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Asset</th>
              <th scope="col">Positions</th>
              <th scope="col">Net direction</th>
              <th scope="col">Gross</th>
              <th scope="col">Net</th>
              <th scope="col">Share of gross</th>
              <th scope="col">Advisor Brief stance</th>
              <th scope="col">Relation to the brief</th>
            </tr>
          </thead>
          <tbody>
            {data.assets.map((a) => (
              <tr key={a.asset}>
                <th scope="row">
                  <Link href={advisorHref(a.asset)}>{a.asset}</Link>
                </th>
                <td>{a.position_count}</td>
                <td>{a.net_direction.replace(/_/g, " ")}</td>
                <td>{usd(a.gross_notional)}</td>
                <td>{usd(a.net_notional)}</td>
                <td>{formatShare(a.share_of_gross)}</td>
                <td>
                  <BriefCell asset={a} />
                </td>
                <td>
                  {relationLabel(a.brief_relation)}
                  {a.disagreement === true ? (
                    <>
                      {" "}
                      <span className="badge badge-warn">Disagrees with the brief</span>
                    </>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Shares are rounded for display and may not add to exactly 100%. Open an asset to read its
        full brief, including risks and invalidation conditions.
      </p>
    </section>
  );
}

function Positions({ data }: { data: PortfolioExposure }) {
  return (
    <section aria-labelledby="exposure-positions-title" data-testid="exposure-positions">
      <h3 id="exposure-positions-title">Open simulated positions</h3>
      <div className="table-scroll">
        <table className="status-table">
          <thead>
            <tr>
              <th scope="col">Trade</th>
              <th scope="col">Asset</th>
              <th scope="col">Direction</th>
              <th scope="col">Notional</th>
              <th scope="col">Leverage</th>
              <th scope="col">Margin</th>
              <th scope="col">Price</th>
              <th scope="col">Relation to the brief</th>
            </tr>
          </thead>
          <tbody>
            {data.positions.map((p) => (
              <tr key={p.trade_id}>
                <th scope="row">{p.trade_id}</th>
                <td>{p.asset}</td>
                <td>{p.direction}</td>
                <td>{usd(p.notional)}</td>
                <td>{formatDecimal(p.leverage, 2)}×</td>
                <td>{usd(p.margin)}</td>
                <td>
                  {p.price_status === "ok" ? (
                    priceStatusLabel(p.price_status)
                  ) : (
                    <span className="badge badge-warn">{priceStatusLabel(p.price_status)}</span>
                  )}
                </td>
                <td>
                  {relationLabel(p.brief_relation)}
                  {p.disagreement === true ? (
                    <>
                      {" "}
                      <span className="badge badge-warn">Disagrees</span>
                    </>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function DataQuality({ data }: { data: PortfolioExposure }) {
  const dq = data.data_quality;
  const invalid = data.invalid_positions;
  if (!dq.has_gaps && invalid.length === 0) {
    return (
      <p className="muted" data-testid="exposure-no-gaps">
        No data gaps reported for this view.
      </p>
    );
  }
  return (
    <section aria-labelledby="exposure-gaps-title" data-testid="exposure-gaps">
      <h3 id="exposure-gaps-title">
        Data gaps <span className="badge badge-warn">Treat the figures as incomplete</span>
      </h3>
      <ul className="decision-missing">
        {dq.positions_missing_price > 0 ? (
          <li>
            {dq.positions_missing_price} position(s) have no observed price. Their notional is still
            counted because it is fixed at entry.
          </li>
        ) : null}
        {dq.assets_without_assessed_brief.length > 0 ? (
          <li>
            No usable Advisor Brief for {dq.assets_without_assessed_brief.join(", ")}. Not assessed
            is not the same as neutral.
          </li>
        ) : null}
        {invalid.map((p) => (
          <li key={p.trade_id}>
            Trade {p.trade_id} was excluded from every figure above:{" "}
            {p.reasons.map(invalidReasonLabel).join("; ") || "reason not given"}.
          </li>
        ))}
      </ul>
    </section>
  );
}

function Unavailables({ data }: { data: PortfolioExposure }) {
  if (data.unavailable.length === 0) return null;
  return (
    <section aria-labelledby="exposure-unavailable-title" data-testid="exposure-unavailable">
      <h3 id="exposure-unavailable-title">Not available on this platform</h3>
      <ul className="note-list">
        {data.unavailable.map((u) => (
          <li key={u.id}>
            <strong>{u.what}</strong> — {u.reason}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Disclosures({ data }: { data: PortfolioExposure }) {
  return (
    <>
      <details className="decision-disclosure" data-testid="exposure-conventions">
        <summary>How these figures are calculated</summary>
        {data.conventions.length === 0 ? (
          <p className="muted">The service returned no conventions.</p>
        ) : (
          <ul className="note-list">
            {data.conventions.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        )}
      </details>
      <details className="decision-disclosure" data-testid="exposure-not-claimed">
        <summary>What this view does not claim</summary>
        {data.not_claimed.length === 0 ? (
          <p className="muted">
            The service returned no statements. Regardless, these are simulated trades, not real
            holdings; this is not a prediction, not personalized advice and not a trade.
          </p>
        ) : (
          <ul className="note-list">
            {data.not_claimed.map((n) => (
              <li key={n.id}>{n.text}</li>
            ))}
          </ul>
        )}
      </details>
    </>
  );
}

/** The exposure for an already-fetched result (pure; the fetching wrapper is below). */
export function PortfolioExposureView({ result }: { result: ApiResult<PortfolioExposure> }) {
  if (!result.ok) return <Frame>{errorPanel(result)}</Frame>;
  const data = result.data;
  const empty = data.summary.status === "empty";
  return (
    <Frame>
      <p className="muted" data-testid="exposure-source">
        {data.source.label} · {data.source.positions_received} open position(s) read,{" "}
        {data.source.positions_invalid} excluded as invalid.
      </p>
      {empty ? (
        <div className="decision-callout" role="status" data-testid="exposure-empty">
          <p>
            <strong>No valid open paper trades.</strong> There is no simulated exposure to show.
            Open a position on the <Link href="/paper">Paper Trading</Link> page to see it here.
          </p>
        </div>
      ) : (
        <>
          <Summary data={data} />
          <Assets data={data} />
          <Positions data={data} />
        </>
      )}
      <DataQuality data={data} />
      <Unavailables data={data} />
      <Disclosures data={data} />
    </Frame>
  );
}

export async function PortfolioExposureSection() {
  const result = await fetchPortfolioExposure();
  return <PortfolioExposureView result={result} />;
}

export function PortfolioExposureLoading() {
  return (
    <section className="status-card decision-center" aria-busy="true">
      <h2>Paper Portfolio Exposure</h2>
      <p className="muted" role="status">
        Loading the simulated exposure…
      </p>
    </section>
  );
}
