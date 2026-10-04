import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const chatProps: Record<string, unknown>[] = [];
vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  CopilotChat: (props: Record<string, unknown>) => {
    chatProps.push(props);
    return null;
  },
  HttpAgent: class {},
  useAgent: () => ({ agent: { subscribe: () => ({ unsubscribe: () => undefined }) } }),
}));
vi.mock("../layout/IntelligenceSlot", () => ({ useIntelligenceSlot: () => undefined }));

import { ClientWorkspace } from "./ClientWorkspace";

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/clients/${id}`]}>
      <Routes>
        <Route path="/clients/:id" element={<ClientWorkspace />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ClientWorkspace", () => {
  it("renders the client's profile and computed P&L in the header", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
        positions: [], unpriced_tickers: [],
      }),
    }));
    renderAt("12");
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText(/VIP/)).toBeInTheDocument();
  });

  it("shows 'no position' copy when totals is null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], unpriced_tickers: [],
      }),
    }));
    renderAt("12");
    expect(await screen.findByText(/no position/i)).toBeInTheDocument();
  });

  it("passes a client-scoped threadId to CopilotChat", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], unpriced_tickers: [],
      }),
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(chatProps[chatProps.length - 1].threadId).toBe("clients_12");
  });

  it("shows an error banner when the summary fetch fails (e.g. a non-numeric id)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({}) }));
    renderAt("not-a-number");
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
  });
});
