import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PortfolioTable } from "./PortfolioTable";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "portfolio_table" }> = {
  type: "portfolio_table",
  positions: [
    { ticker: "BND", shares: 300, price: 70.63, market_value: 21189, cost_basis: 21999,
      unrealized_pnl: -810, unrealized_pnl_pct: -3.68, weight_pct: 13.62, sector: "ETF" },
    { ticker: "NVDA", shares: 71, price: 1259.66, market_value: 89436, cost_basis: 12280,
      unrealized_pnl: 77156, unrealized_pnl_pct: 628.31, weight_pct: 57.5, sector: "Technology" },
  ],
  totals: { market_value: 155564.81, cost_basis: 64179, unrealized_pnl: 91385.81, unrealized_pnl_pct: 142.39 },
};

describe("PortfolioTable", () => {
  it("shows one row per position with ticker and weight", () => {
    render(<PortfolioTable display={display} />);
    expect(screen.getByText("BND")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("13.62%")).toBeInTheDocument();
  });

  it("shows the portfolio total market value", () => {
    render(<PortfolioTable display={display} />);
    expect(screen.getByText(/\$155,564\.81/)).toBeInTheDocument();
  });

  it("colors a losing position's P&L differently from a winning one", () => {
    render(<PortfolioTable display={display} />);
    const loss = screen.getByText("-$810.00");
    const gain = screen.getByText("$77,156.00");
    expect(loss.className).toContain("terminal-danger");
    expect(gain.className).toContain("terminal-accent");
  });
});
