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

  it("omits the concentration alert when there are zero breaches (not just when null)", async () => {
    // Regression (final review finding 2): ConcentrationAlert has no empty
    // state -- rendering it whenever `concentration` is non-null (even with
    // breaches: []) drew an amber "Concentration > 30%" box for every
    // normal, well-diversified client.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ ...FULL_REPORT, concentration: { threshold_pct: 30, breach_count: 0, breaches: [] } }),
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(screen.queryByText(/Concentration/)).not.toBeInTheDocument();
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

  it("shows 'Prices unavailable' instead of 'No position.' when every ticker failed to price", async () => {
    // Regression (final review finding 3): ReportWorkspace merged
    // chantier 2's three header branches (totals / Prices unavailable /
    // No position.) into two, so a full yfinance outage told the advisor
    // the client holds nothing instead of flagging the outage.
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        ...FULL_REPORT, totals: null, positions: [], sector_allocation: null,
        concentration: null, price_history: {}, unpriced_tickers: ["AAPL"],
      }),
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(screen.getAllByText(/prices unavailable/i).length).toBeGreaterThan(0);
    expect(screen.queryByText(/no position/i)).not.toBeInTheDocument();
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
    await screen.findByText("Jane Doe");
    expect(screen.getAllByText(/no position/i).length).toBeGreaterThan(0);
  });

  it("clicking Generate report calls generateClientReport and re-fetches on success", async () => {
    // Regression (final review finding 5): the original version of this
    // test only checked that a POST happened -- it still passed with
    // load() removed from onGenerate. This asserts the GET actually ran
    // again (2 GETs, not 1) and that the newly generated file shows up.
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    let getCount = 0;
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        return Promise.resolve({ ok: true, json: async () => ({ filename: "new-file.xlsx" }) });
      }
      getCount += 1;
      const generated_reports = getCount >= 2
        ? [...FULL_REPORT.generated_reports, { filename: "new-file.xlsx", generated_at: "2026-01-02T00:00:00+00:00", download_url: "/workspace/files/new-file.xlsx" }]
        : FULL_REPORT.generated_reports;
      return Promise.resolve({ ok: true, json: async () => ({ ...FULL_REPORT, generated_reports }) });
    }));
    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /generate report/i }));
    expect(await screen.findByText("new-file.xlsx")).toBeInTheDocument();
    expect(getCount).toBe(2);
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
