import { describe, expect, it } from "vitest";
import { lastCardContext } from "./lastCardContext";

const tool = (displays: unknown[]) => ({ role: "tool", content: JSON.stringify({ summary: "s", displays }) });

describe("lastCardContext", () => {
  it("summarizes the most recent card's key fields", () => {
    const msgs = [
      tool([{ type: "watchlist_alerts", near_pct: 5, rows: [{ client: "Ann" }], unpriced: [] }]),
      { role: "assistant", content: "ok" },
      tool([{ type: "company_comparison", period: "6mo", missing: [], companies: [{ symbol: "NVDA" }, { symbol: "AMD" }] }]),
    ];
    expect(lastCardContext(msgs)).toBe('{"card":"company_comparison","symbols":["NVDA","AMD"],"period":"6mo"}');
  });

  it("describes a what-if by client and trades", () => {
    const msgs = [tool([{ type: "what_if", client_name: "Margaret Collins", before: {}, after: {}, cash_delta: 0,
      breaches_before: [], breaches_after: [], trades: [{ ticker: "NVDA", action: "sell", shares: 50, price: 1 }] }])];
    expect(lastCardContext(msgs)).toBe('{"card":"what_if","client":"Margaret Collins","trades":["sell 50 NVDA"]}');
  });

  it("returns null without cards", () => {
    expect(lastCardContext([{ role: "user", content: "hi" }])).toBeNull();
  });
});
