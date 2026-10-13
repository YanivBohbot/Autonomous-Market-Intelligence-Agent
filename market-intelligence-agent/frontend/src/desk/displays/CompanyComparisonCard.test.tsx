import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CompanyComparisonCard, mergeSeries } from "./CompanyComparisonCard";
import type { DisplayPayload } from "./types";

const company = (symbol: string, ret: number) => ({
  symbol, name: `${symbol} Inc.`, sector: "Technology", currency: "USD", price: 100, market_cap: 2.5e12,
  trailing_pe: 40, forward_pe: null, range_position_pct: 75, period_return_pct: ret,
  points: [{ date: "2026-04-01", value: 100 }, { date: "2026-10-01", value: 100 + ret }],
});
const display: Extract<DisplayPayload, { type: "company_comparison" }> = {
  type: "company_comparison", period: "6mo", missing: ["ZZZZ"], companies: [company("NVDA", 42.5), company("AMD", -3.1)],
};

describe("CompanyComparisonCard", () => {
  it("shows one column per company with its metrics", () => {
    render(<CompanyComparisonCard display={display} />);
    expect(screen.getByRole("columnheader", { name: "NVDA" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "AMD" })).toBeInTheDocument();
    expect(screen.getByText("+42.5%")).toBeInTheDocument();
    expect(screen.getByText("-3.1%")).toBeInTheDocument();
    expect(screen.getAllByText("$2.50T")).toHaveLength(2);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0); // null forward P/E
    expect(screen.getByText(/No data for ZZZZ/)).toBeInTheDocument();
  });

  it("merges the rebased series by date for the chart", () => {
    expect(mergeSeries(display.companies)).toEqual([
      { date: "2026-04-01", NVDA: 100, AMD: 100 },
      { date: "2026-10-01", NVDA: 142.5, AMD: 96.9 },
    ]);
  });
});
