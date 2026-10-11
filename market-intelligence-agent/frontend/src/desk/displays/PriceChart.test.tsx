import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceChart, formatAxisDate } from "./PriceChart";
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

describe("formatAxisDate", () => {
  it("shortens an ISO date to MM-DD so the last x-axis tick fits inside the chart", () => {
    // Regression (live QA): a full "2026-10-02" tick label on the
    // rightmost point got clipped by the chart's edge (Recharts' default
    // 5px right margin isn't wide enough for a 10-character label
    // anchored at the plot's last data point).
    expect(formatAxisDate("2026-10-02")).toBe("10-02");
  });

  it("leaves a non-ISO string unchanged instead of mangling it", () => {
    expect(formatAxisDate("N/A")).toBe("N/A");
  });
});
