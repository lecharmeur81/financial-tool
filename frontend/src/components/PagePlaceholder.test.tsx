import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { navItem } from "@/lib/navigation";

import { PagePlaceholder } from "./PagePlaceholder";

afterEach(cleanup);

describe("PagePlaceholder", () => {
  it("shows the section and states that no data is connected", () => {
    render(<PagePlaceholder item={navItem("/liquidity")} />);
    expect(screen.getByRole("heading", { level: 1, name: "Liquidity" })).toBeDefined();
    expect(screen.getByText("No data sources connected")).toBeDefined();
    expect(screen.getByText("Planned phase: not yet scheduled")).toBeDefined();
  });

  it("does not display any numbers as data", () => {
    const { container } = render(<PagePlaceholder item={navItem("/flows")} />);
    const text = container.querySelector(".placeholder")?.textContent ?? "";
    // The only digits allowed are the planned phase reference.
    expect(text.replace(/Planned phase: [\d–\s()a-z]+/i, "")).not.toMatch(/\d/);
  });
});
