import { describe, it, expect } from "vitest";
import { parseDisplay } from "./parseDisplay";

const portfolioTable = {
  type: "portfolio_table",
  positions: [{ ticker: "BND", shares: 300, price: 70.63, market_value: 21189, cost_basis: 21999,
                unrealized_pnl: -810, unrealized_pnl_pct: -3.68, weight_pct: 13.62, sector: "ETF" }],
  totals: { market_value: 21189, cost_basis: 21999, unrealized_pnl: -810, unrealized_pnl_pct: -3.68 },
};

describe("parseDisplay", () => {
  it("returns the envelope for a valid payload", () => {
    const envelope = parseDisplay(JSON.stringify({ summary: "text", displays: [portfolioTable] }));
    expect(envelope).toEqual({ summary: "text", displays: [portfolioTable] });
  });

  it("returns null for text that isn't JSON", () => {
    expect(parseDisplay("plain tool text, no envelope")).toBeNull();
  });

  it("returns null when there is no displays array", () => {
    expect(parseDisplay(JSON.stringify({ summary: "text" }))).toBeNull();
  });

  it("drops an entry with an unknown type but keeps the valid ones", () => {
    const envelope = parseDisplay(JSON.stringify({
      summary: "text",
      displays: [portfolioTable, { type: "some_future_type", whatever: 1 }],
    }));
    expect(envelope?.displays).toEqual([portfolioTable]);
  });

  it("drops an entry of a known type missing a required field", () => {
    const envelope = parseDisplay(JSON.stringify({
      summary: "text",
      displays: [portfolioTable, { type: "screenshot" }],  // missing "url"
    }));
    expect(envelope?.displays).toEqual([portfolioTable]);
  });

  it("returns an envelope with an empty displays list rather than null", () => {
    expect(parseDisplay(JSON.stringify({ summary: "text", displays: [] }))).toEqual({ summary: "text", displays: [] });
  });
});
