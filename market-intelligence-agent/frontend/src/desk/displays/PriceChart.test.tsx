import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceChart } from "./PriceChart";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "price_chart" }> = {
  type: "price_chart",
  ticker: "AAPL",
  points: [
    { date: "2026-09-21", close: 338.98 },
    { date: "2026-09-22", close: 339.75 },
    { date: "2026-09-23", close: 337.02 },
  ],
};

describe("PriceChart", () => {
  it("shows the ticker in the title", () => {
    render(<PriceChart display={display} />);
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
  });

  it("renders a chart container for each point (smoke test via recharts' surface)", () => {
    const { container } = render(<PriceChart display={display} />);
    expect(container.querySelector(".recharts-responsive-container")).toBeInTheDocument();
  });
});
