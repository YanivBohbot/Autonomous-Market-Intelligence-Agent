import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReportWorkspace } from "./ReportWorkspace";

function renderAt(id: string) {
  return render(
    <MemoryRouter initialEntries={[`/reports/${id}`]}>
      <Routes>
        <Route path="/reports/:id" element={<ReportWorkspace />} />
      </Routes>
    </MemoryRouter>,
  );
}

const FULL_REPORT = {
  client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
  risk_profile: "balanced", advisor: "Sam", city: "Paris",
  totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
  positions: [
    { ticker: "AAPL", shares: 10, price: 200, sector: "Technology", market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33, weight_pct: 100 },
  ],
  sector_allocation: { Technology: 100 },
  concentration: { threshold_pct: 30, breach_count: 1, breaches: [{ label: "Jane Doe", ticker: "AAPL", weight_pct: 100, market_value: 2000 }] },
  price_history: { AAPL: [{ date: "2026-09-21", close: 338.98 }] },
  unpriced_tickers: [],
  generated_reports: [{ filename: "jane-doe-portfolio-brief-2026-01-01.xlsx", generated_at: "2026-01-01T00:00:00+00:00", download_url: "/workspace/files/jane-doe-portfolio-brief-2026-01-01.xlsx" }],
};

describe("ReportWorkspace", () => {
  it("renders every section when every field is populated", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => FULL_REPORT }));
    renderAt("12");
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument(); // SectorAllocationChart
    expect(screen.getByText(/Concentration/)).toBeInTheDocument(); // ConcentrationAlert
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0); // appears in pie/table/alert/price chart
    expect(screen.getByText("jane-doe-portfolio-brief-2026-01-01.xlsx")).toBeInTheDocument(); // ReportFileCard
    expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/reports");
  });

  it("omits the sector chart and concentration alert when both are null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...FULL_REPORT, sector_allocation: null, concentration: null }),
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(screen.queryByText("Technology")).not.toBeInTheDocument();
    expect(screen.queryByText(/Concentration/)).not.toBeInTheDocument();
  });

  it("shows 'No position.' when totals is null", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...FULL_REPORT, totals: null, positions: [], sector_allocation: null,
        concentration: null, price_history: {},
      }),
    }));
    renderAt("12");
    expect(await screen.findByText(/no position/i)).toBeInTheDocument();
  });

  it("clicking Generate report calls generateClientReport and re-fetches on success", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    let generateCalled = false;
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        generateCalled = true;
        return Promise.resolve({ ok: true, json: async () => ({ filename: "new-file.xlsx" }) });
      }
      return Promise.resolve({ ok: true, json: async () => FULL_REPORT });
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /generate report/i }));
    await waitFor(() => expect(generateCalled).toBe(true));
  });

  it("shows the thrown error message inline when Generate report fails", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve({ ok: false, status: 502, json: async () => ({ detail: "could not price: AAPL" }) });
      }
      return Promise.resolve({ ok: true, json: async () => FULL_REPORT });
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /generate report/i }));
    expect(await screen.findByText(/could not price: AAPL/i)).toBeInTheDocument();
  });

  it("shows an error banner with a link back to /reports when the report fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }));
    renderAt("999");
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/reports");
  });
});
