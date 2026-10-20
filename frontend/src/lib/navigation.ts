/**
 * Application navigation. Each entry must have a matching page under src/app (enforced by a test).
 * `plannedPhase` is provisional — phase numbers from 3 onward follow the user's guide (CLAUDE.md §C3).
 */
export const NAV_GROUPS = [
  "Overview",
  "Intelligence",
  "Decision support",
  "Records",
  "System",
] as const;
export type NavGroup = (typeof NAV_GROUPS)[number];

export type NavItem = {
  href: string;
  label: string;
  group: NavGroup;
  description: string;
  plannedPhase: string;
};

export const NAV_ITEMS: readonly NavItem[] = [
  {
    href: "/",
    label: "Dashboard",
    group: "Overview",
    description:
      "Executive overview: market regime, capital-flow divergences, key changes, and data quality.",
    plannedPhase: "26",
  },
  {
    href: "/market",
    label: "Market",
    group: "Intelligence",
    description:
      "Spot prices, candles and volume by venue, and market capitalisation — with source, freshness, and missing-data warnings.",
    plannedPhase: "5 (market data); market structure later",
  },
  {
    href: "/flows",
    label: "Flows",
    group: "Intelligence",
    description:
      "Institutional capital: US spot ETF flows (BTC, ETH, SOL, XRP), corporate treasuries and the transparent Institutional Flow Score — with evidence class shown for every actor label.",
    plannedPhase: "6 (institutional capital)",
  },
  {
    href: "/whales",
    label: "Whales",
    group: "Intelligence",
    description:
      "Whale intelligence: exchange inflows and outflows, largest addresses with evidence-based labels, large transfers, dormant-coin and miner activity, the Whale Flow Score and contradiction indicators (BTC, ETH).",
    plannedPhase: "7 (whale intelligence)",
  },
  {
    href: "/derivatives",
    label: "Derivatives",
    group: "Intelligence",
    description:
      "Derivatives: open interest and leverage, funding, futures basis, liquidations, options positioning and the transparent Derivatives Health Score (BTC, ETH, SOL, XRP; options BTC, ETH).",
    plannedPhase: "8 (derivatives)",
  },
  {
    href: "/liquidity",
    label: "Liquidity",
    group: "Intelligence",
    description:
      "Stablecoin circulating supply and growth, market share, growth acceleration, and the transparent Liquidity Score, with daily supply history.",
    plannedPhase: "9 (liquidity); order-book depth and macro liquidity later",
  },
  {
    href: "/analytics",
    label: "Analytics",
    group: "Intelligence",
    description:
      "Market regime, capital-flow divergences, anomalies, capital rotation, historical similarity, and recent intelligence events — each reusing its own engine's output unchanged.",
    plannedPhase: "12–15, 19, 20, 35 (backtests not yet scheduled)",
  },
  {
    href: "/advisor",
    label: "Advisor Brief",
    group: "Decision support",
    description:
      "Read-only, rule-based brief per asset: stance, evidence layers, data gaps, risks and invalidation conditions from the latest stored snapshot. Not a prediction, not personalized advice, no trading.",
    plannedPhase: "53",
  },
  {
    href: "/portfolio",
    label: "Portfolio Exposure",
    group: "Decision support",
    description:
      "Read-only exposure of your simulated paper trades — gross, net, concentration and leverage — compared with the Advisor Brief. Simulated only: not real holdings, not advice, no trading.",
    plannedPhase: "54, 55",
  },
  {
    href: "/alerts",
    label: "Alerts",
    group: "Decision support",
    description: "Rule-based alerts on metrics, signals, regimes, and data-quality events.",
    plannedPhase: "23",
  },
  {
    href: "/brief",
    label: "Daily Brief",
    group: "Decision support",
    description:
      "The latest AI Analyst Daily Market Brief: summary, evidence, contradicting evidence, regime, key changes, risks, scenarios, invalidation conditions, and data quality.",
    plannedPhase: "22",
  },
  {
    href: "/paper",
    label: "Paper Trading",
    group: "Records",
    description:
      "Simulated trades only — open positions, performance, and trade history. No real execution.",
    plannedPhase: "24",
  },
  {
    href: "/journal",
    label: "Decision Journal",
    group: "Records",
    description:
      "Your own recorded decisions — thesis, decision-time evidence, and later outcomes. Descriptive review only, never a ranking.",
    plannedPhase: "25",
  },
  {
    href: "/settings",
    label: "Settings",
    group: "System",
    description:
      "System readiness, service metadata, provider health, and recent ingestion runs. Account and security settings not yet built.",
    plannedPhase: "3, 36 (operational status); account and security settings later",
  },
] as const;

/** The items grouped for display, in navigation order (a group appears where its first item is). */
export function navGroups(): { group: NavGroup; items: NavItem[] }[] {
  return NAV_GROUPS.map((group) => ({
    group,
    items: NAV_ITEMS.filter((item) => item.group === group),
  })).filter((g) => g.items.length > 0);
}

export function isActive(itemHref: string, pathname: string): boolean {
  if (itemHref === "/") return pathname === "/";
  return pathname === itemHref || pathname.startsWith(`${itemHref}/`);
}

export function navItem(href: string): NavItem {
  const item = NAV_ITEMS.find((i) => i.href === href);
  if (!item) throw new Error(`Unknown navigation item: ${href}`);
  return item;
}
