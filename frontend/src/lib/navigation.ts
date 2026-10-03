/**
 * Application navigation. Each entry must have a matching page under src/app (enforced by a test).
 * `plannedPhase` is provisional — phase numbers from 3 onward follow the user's guide (CLAUDE.md §C3).
 */
export type NavItem = {
  href: string;
  label: string;
  description: string;
  plannedPhase: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/",
    label: "Dashboard",
    description:
      "Executive overview: market regime, capital-flow divergences, key changes, and data quality.",
    plannedPhase: "26",
  },
  {
    href: "/market",
    label: "Market",
    description:
      "Spot prices, candles and volume by venue, and market capitalisation — with source, freshness, and missing-data warnings.",
    plannedPhase: "5 (market data); market structure later",
  },
  {
    href: "/flows",
    label: "Flows",
    description:
      "Institutional capital: US spot ETF flows (BTC, ETH, SOL, XRP), corporate treasuries and the transparent Institutional Flow Score — with evidence class shown for every actor label.",
    plannedPhase: "6 (institutional capital)",
  },
  {
    href: "/whales",
    label: "Whales",
    description:
      "Whale intelligence: exchange inflows and outflows, largest addresses with evidence-based labels, large transfers, dormant-coin and miner activity, the Whale Flow Score and contradiction indicators (BTC, ETH).",
    plannedPhase: "7 (whale intelligence)",
  },
  {
    href: "/derivatives",
    label: "Derivatives",
    description:
      "Derivatives: open interest and leverage, funding, futures basis, liquidations, options positioning and the transparent Derivatives Health Score (BTC, ETH, SOL, XRP; options BTC, ETH).",
    plannedPhase: "8 (derivatives)",
  },
  {
    href: "/liquidity",
    label: "Liquidity",
    description: "Stablecoin supply and exchange balances, order-book depth, and macro liquidity.",
    plannedPhase: "not yet scheduled",
  },
  {
    href: "/analytics",
    label: "Analytics",
    description:
      "Divergences, regimes, historical similarity, anomalies, capital rotation, and backtests.",
    plannedPhase: "12–18",
  },
  {
    href: "/alerts",
    label: "Alerts",
    description: "Rule-based alerts on metrics, signals, regimes, and data-quality events.",
    plannedPhase: "23",
  },
  {
    href: "/brief",
    label: "Daily Brief",
    description:
      "The latest AI Analyst Daily Market Brief: summary, evidence, contradicting evidence, regime, key changes, risks, scenarios, invalidation conditions, and data quality.",
    plannedPhase: "22",
  },
  {
    href: "/paper",
    label: "Paper Trading",
    description:
      "Simulated trades only — open positions, performance, and trade history. No real execution.",
    plannedPhase: "24",
  },
  {
    href: "/journal",
    label: "Decision Journal",
    description:
      "Your own recorded decisions — thesis, decision-time evidence, and later outcomes. Descriptive review only, never a ranking.",
    plannedPhase: "25",
  },
  {
    href: "/settings",
    label: "Settings",
    description: "System status, preferences, and (later) account and security settings.",
    plannedPhase: "3 (status only)",
  },
] as const;

export function isActive(itemHref: string, pathname: string): boolean {
  if (itemHref === "/") return pathname === "/";
  return pathname === itemHref || pathname.startsWith(`${itemHref}/`);
}

export function navItem(href: string): NavItem {
  const item = NAV_ITEMS.find((i) => i.href === href);
  if (!item) throw new Error(`Unknown navigation item: ${href}`);
  return item;
}
