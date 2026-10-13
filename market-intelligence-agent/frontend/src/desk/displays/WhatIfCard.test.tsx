import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { WhatIfCard } from "./WhatIfCard";
import type { DisplayPayload } from "./types";

const totals = (mv: number) => ({ market_value: mv, cost_basis: 1, unrealized_pnl: 0, unrealized_pnl_pct: 0 });
const display: Extract<DisplayPayload, { type: "what_if" }> = {
  type: "what_if", client_name: "Margaret Collins", cash_delta: 10000,
  before: { totals: totals(27000), positions: [{ ticker: "NVDA", weight_pct: 74.07, market_value: 20000 }, { ticker: "BND", weight_pct: 25.93, market_value: 7000 }] },
  after: { totals: totals(17000), positions: [{ ticker: "BND", weight_pct: 100, market_value: 7000 }] },
  breaches_before: ["NVDA"], breaches_after: [],
  trades: [{ ticker: "NVDA", action: "sell", shares: 100, price: 200 }],
};

describe("WhatIfCard", () => {
  it("shows before/after weights, cash raised and a resolved concentration", () => {
    render(<WhatIfCard display={display} />);
    expect(screen.getByText(/Margaret Collins/)).toBeInTheDocument();
    expect(screen.getByText(/Sell 100 NVDA/)).toBeInTheDocument();
    expect(screen.getByText("74.1%")).toBeInTheDocument();
    expect(screen.getByText("0.0%")).toBeInTheDocument(); // NVDA after: closed
    expect(screen.getByText(/Cash raised/)).toBeInTheDocument();
    expect(screen.getByText(/NVDA concentration resolved/)).toBeInTheDocument();
    expect(screen.getByText(/Simulation/)).toBeInTheDocument();
  });
});
