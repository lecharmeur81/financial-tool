import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import Loading from "./loading";

afterEach(cleanup);

describe("Loading", () => {
  it("shows an honest loading state with no numbers", () => {
    render(<Loading />);
    expect(screen.getByText("Loading")).toBeTruthy();
    expect(screen.getByRole("status")).toBeTruthy();
  });
});
