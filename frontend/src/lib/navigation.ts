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
    plannedPhase: "24",
  },
  {
    href: "/market",
    label: "Market",
    description: "Spot prices, volume by venue, volatility, dominance, and market structure.",
    plannedPhase: "4 and 11",
  },
  {
    href: "/flows",
    label: "Flows",
    description:
      "Institutional flows (ETFs, regulated venues), whale activity, and exchange inflows/outflows — with evidence class shown for every actor label.",
    plannedPhase: "5–6",
  },
  {
    href: "/derivatives",
    label: "Derivatives",
    description: "Open interest, funding, liquidations, basis, and options positioning.",
    plannedPhase: "7",
  },
  {
    href: "/liquidity",
    label: "Liquidity",
    description: "Stablecoin supply and exchange balances, order-book depth, and macro liquidity.",
    plannedPhase: "8 and 10",
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
    plannedPhase: "21",
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
