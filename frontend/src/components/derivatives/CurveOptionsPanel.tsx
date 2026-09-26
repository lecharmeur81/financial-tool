import { type DerivativesAssetView, formatPct, formatPoints, hasDetail } from "@/lib/derivatives";
import { formatNumber } from "@/lib/institutional";

/** Deribit futures curve (basis) and option positioning (put/call, ATM IV, skew, DVOL). */
export function CurveOptionsPanel({ view }: { view: DerivativesAssetView }) {
  const basis = view.basis;
  const options = view.options;
  const vol = view.volatility;
  return (
    <section className="status-card" aria-labelledby="deriv-curve-title">
      <h2 id="deriv-curve-title">Futures basis and options</h2>
      <h3>Futures basis (Deribit)</h3>
      {!hasDetail(basis) ? (
        <p role="status">{basis.reason}</p>
      ) : (
        <>
          {basis.headline ? (
            <p>
              Headline {basis.headline.instrument} ({basis.headline.days_to_expiry} days):{" "}
              {formatPct(basis.headline.annualised_pct)} a year · {basis.shape} ·{" "}
              <strong>{basis.condition}</strong> · perpetual premium{" "}
              {formatPct(basis.perpetual_premium_pct, 4)}
            </p>
          ) : (
            <p role="status">Insufficient data: {basis.reason}</p>
          )}
          <p className="muted">
            {basis.calculation}. Snapshot {basis.snapshot ?? "—"}.
          </p>
          {basis.curve.length ? (
            <table className="status-table">
              <thead>
                <tr>
                  <th scope="col">Future</th>
                  <th scope="col">Days</th>
                  <th scope="col">Mark</th>
                  <th scope="col">Index</th>
                  <th scope="col">Premium</th>
                  <th scope="col">Annualised</th>
                </tr>
              </thead>
              <tbody>
                {basis.curve.map((c) => (
                  <tr key={c.instrument}>
                    <th scope="row">{c.instrument}</th>
                    <td>{c.days_to_expiry ?? "—"}</td>
                    <td>{formatNumber(c.mark, 2)}</td>
                    <td>{formatNumber(c.index, 2)}</td>
                    <td>{formatPct(c.premium_pct, 4)}</td>
                    <td>
                      {c.annualised_pct === null ? "— (< 1 day)" : formatPct(c.annualised_pct)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : null}
        </>
      )}

      <h3>Options (Deribit)</h3>
      {!hasDetail(options) ? (
        <p role="status">{options.reason}</p>
      ) : options.status !== "ok" ? (
        <p role="status">Insufficient data: {options.reason}</p>
      ) : (
        <>
          <ul className="note-list">
            <li>
              Open interest: calls {formatNumber(options.call_open_interest, 1)}, puts{" "}
              {formatNumber(options.put_open_interest, 1)} contracts · put/call{" "}
              {options.put_call_oi_ratio ?? "—"}
              {options.notional_open_interest_usd
                ? ` · notional ≈ $${formatNumber(options.notional_open_interest_usd)}`
                : ""}
            </li>
            <li>
              24 h volume: calls {formatNumber(options.call_volume_24h, 1)}, puts{" "}
              {formatNumber(options.put_volume_24h, 1)} · put/call{" "}
              {options.put_call_volume_ratio ?? "—"}
            </li>
            <li>
              Expiry {options.expiry ?? "—"} ({options.expiry_days ?? "—"} days), forward{" "}
              {formatNumber(options.forward, 2)}: ATM implied volatility {options.atm_iv_pct ?? "—"}{" "}
              % (strike {formatNumber(options.atm_strike)})
            </li>
            <li>
              Skew:{" "}
              {options.skew_pct_points === null
                ? `insufficient data (${options.skew_reason})`
                : `${formatPoints(options.skew_pct_points)} — put ${formatNumber(options.skew_put?.strike ?? null)} at ${options.skew_put?.iv_pct} % vs call ${formatNumber(options.skew_call?.strike ?? null)} at ${options.skew_call?.iv_pct} %; ${options.skew_context}`}
            </li>
          </ul>
          <ul className="note-list muted">
            {Object.entries(options.definitions).map(([k, v]) => (
              <li key={k}>
                {k}: {v}
              </li>
            ))}
          </ul>
        </>
      )}

      <h3>Implied volatility index</h3>
      {"dvol_pct" in vol ? (
        <p>
          {vol.index}: {vol.dvol_pct} % (hour {vol.hour}), 7 d change{" "}
          {formatPoints(vol.change_7d_points)}
        </p>
      ) : (
        <p role="status">{vol.reason}</p>
      )}
    </section>
  );
}
