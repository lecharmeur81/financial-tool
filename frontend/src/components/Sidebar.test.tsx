import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NAV_ITEMS } from "@/lib/navigation";

import { Sidebar } from "./Sidebar";

const pathname = vi.hoisted(() => ({ current: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => pathname.current }));

afterEach(cleanup);

describe("Sidebar", () => {
  it("renders all navigation links", () => {
    render(<Sidebar />);
    expect(screen.getAllByRole("link")).toHaveLength(NAV_ITEMS.length);
  });

  it("groups the links under labelled headings without changing the link count", () => {
    render(<Sidebar />);
    const groups = screen.getAllByRole("list");
    expect(groups.map((g) => g.getAttribute("aria-labelledby")).filter(Boolean)).toHaveLength(
      groups.length,
    );
    expect(screen.getByText("Decision support").tagName).toBe("P");
    expect(screen.getByRole("link", { name: "Portfolio Exposure" }).getAttribute("href")).toBe(
      "/portfolio",
    );
  });

  it("marks only the current page", () => {
    pathname.current = "/liquidity";
    render(<Sidebar />);
    const current = screen.getAllByRole("link").filter((a) => a.getAttribute("aria-current"));
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toBe("Liquidity");
  });
});
