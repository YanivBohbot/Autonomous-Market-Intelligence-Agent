import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { TickerInfoCard } from "./TickerInfoCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "ticker_info" }> = {
  type: "ticker_info", ticker: "AAPL", name: "Apple Inc.", sector: "Technology",
  industry: "Consumer Electronics", current_price: 341.07, currency: "USD",
  market_cap: 4977636933632, fifty_two_week_low: 243.42, fifty_two_week_high: 345.34,
};

describe("TickerInfoCard", () => {
  it("shows the name, ticker and current price", () => {
    render(<TickerInfoCard display={display} />);
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText(/AAPL/)).toBeInTheDocument();
    expect(screen.getByText("$341.07")).toBeInTheDocument();
  });

  it("shows the 52-week range", () => {
    render(<TickerInfoCard display={display} />);
    expect(screen.getByText(/243.42/)).toBeInTheDocument();
    expect(screen.getByText(/345.34/)).toBeInTheDocument();
  });

  it("handles a null sector/industry without crashing", () => {
    render(<TickerInfoCard display={{ ...display, sector: null, industry: null }} />);
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
  });
});
