import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PortfolioPieChart } from "./PortfolioPieChart";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "portfolio_chart" }> = {
  type: "portfolio_chart",
  slices: [{ ticker: "BND", weight_pct: 13.62 }, { ticker: "NVDA", weight_pct: 57.5 }],
};

describe("PortfolioPieChart", () => {
  it("renders a legend entry per slice", () => {
    render(<PortfolioPieChart display={display} />);
    expect(screen.getByText(/BND/)).toBeInTheDocument();
    expect(screen.getByText(/NVDA/)).toBeInTheDocument();
  });
});
