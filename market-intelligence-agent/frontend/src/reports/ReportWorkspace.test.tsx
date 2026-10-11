import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
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

const SUMMARY = {
  client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
  risk_profile: "balanced", advisor: "Sam", city: "Paris",
  totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
  positions: [
    { ticker: "AAPL", shares: 10, avg_cost: 150, price: 200, sector: "Technology", market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33, weight_pct: 100 },
  ],
  unpriced_tickers: [],
};

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
  narrative: "Jane Doe's portfolio is concentrated in AAPL, which carries more single-stock risk than a balanced profile would typically target.",
};

function fetchRouter(handlers: { summary?: () => Promise<unknown>; report?: () => Promise<unknown>; generate?: () => Promise<unknown> }) {
  return vi.fn((url: string, init?: RequestInit) => {
    if (init?.method === "POST" && url.includes("/generate")) {
      return (handlers.generate ?? (() => Promise.resolve({ ok: true, json: async () => ({ filename: "new.xlsx" }) })))();
    }
    if (url.includes("/report")) {
      return (handlers.report ?? (() => Promise.resolve({ ok: true, json: async () => FULL_REPORT })))();
    }
    return (handlers.summary ?? (() => Promise.resolve({ ok: true, json: async () => SUMMARY })))();
  });
}

describe("ReportWorkspace", () => {
  it("shows a structured summary skeleton while the summary itself is loading", async () => {
    // Regression (live QA): the page rendered nothing at all (return null)
    // while the summary fetch was in flight -- indistinguishable from a
    // crash or a frozen tab during the several seconds a cold yfinance
    // quote can take.
    let resolveSummary: (v: unknown) => void;
    const summaryPromise = new Promise((resolve) => { resolveSummary = resolve; });
    vi.stubGlobal("fetch", fetchRouter({ summary: () => summaryPromise as Promise<unknown> }));

    renderAt("12");
    expect(screen.getByRole("status", { name: "Loading report profile" })).toBeInTheDocument();
    expect(screen.getAllByRole("status", { name: "Loading report metric" })).toHaveLength(4);

    resolveSummary!({ ok: true, json: async () => SUMMARY });
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading report profile" })).not.toBeInTheDocument();
  });

  it("shows a summary hero and KPIs without crossing the full-report gate", async () => {
    const fetchMock = fetchRouter({});
    vi.stubGlobal("fetch", fetchMock);
    renderAt("12");
    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.getByText("Balanced risk")).toBeInTheDocument();
    expect(screen.getByText("Market value")).toBeInTheDocument();
    expect(screen.getByText("$2,000.00")).toBeInTheDocument();
    expect(screen.getByText("Unrealized P&L")).toBeInTheDocument();
    expect(screen.getByText("+$500.00")).toBeInTheDocument();
    expect(screen.getByText("Return")).toBeInTheDocument();
    expect(screen.getByText("+33.3%")).toBeInTheDocument();
    expect(screen.getByText("Price coverage")).toBeInTheDocument();
    expect(screen.getByText("1 of 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /view full report/i })).toBeInTheDocument();
    const reportCalls = fetchMock.mock.calls.filter(([url]) => String(url).includes("/report") && !String(url).includes("/summary"));
    expect(reportCalls).toHaveLength(0);
  });

  it("shows a loading indicator while the full report loads, then renders the narrative and sections", async () => {
    let resolveReport: (v: unknown) => void;
    const reportPromise = new Promise((resolve) => { resolveReport = resolve; });
    const fetchMock = fetchRouter({ report: () => reportPromise as Promise<unknown> });
    vi.stubGlobal("fetch", fetchMock);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/report") && !String(url).includes("/summary"))).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: /view full report/i }));
    expect(screen.getByRole("status", { name: "Loading full report" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/report") && !String(url).includes("/summary"))).toHaveLength(1);

    resolveReport!({ ok: true, json: async () => FULL_REPORT });
    expect(await screen.findByText(FULL_REPORT.narrative)).toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Loading full report" })).not.toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument(); // SectorAllocationChart
    expect(screen.getAllByText(/Concentration/).length).toBeGreaterThan(0); // section heading + ConcentrationAlert
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getByText("jane-doe-portfolio-brief-2026-01-01.xlsx")).toBeInTheDocument();
    // Each chart section has its own caption -- live QA feedback was "a
    // wall of text, then a wall of unlabeled graphs."
    for (const heading of ["Analysis", "Portfolio allocation", "Sector exposure", "Price trends", "Concentration risk", "Positions", "Generated reports"]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
  });

  it("shows an inline error and keeps the summary visible when the full report fetch fails", async () => {
    const fetchMock = fetchRouter({ report: () => Promise.resolve({ ok: false, status: 500, json: async () => ({}) }) });
    vi.stubGlobal("fetch", fetchMock);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /view full report/i }));
    expect(await screen.findByText(/failed to load the full report/i)).toBeInTheDocument();
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
  });

  it("omits the sector chart and concentration alert when both are null", async () => {
    const fetchMock = fetchRouter({ report: () => Promise.resolve({ ok: true, json: async () => ({ ...FULL_REPORT, sector_allocation: null, concentration: null }) }) });
    vi.stubGlobal("fetch", fetchMock);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /view full report/i }));
    await screen.findByText(FULL_REPORT.narrative);
    expect(screen.queryByText("Technology")).not.toBeInTheDocument();
    expect(screen.queryByText(/Concentration/)).not.toBeInTheDocument();
  });

  it("shows 'Prices unavailable' in the header when every ticker failed to price", async () => {
    const fetchMock = fetchRouter({ summary: () => Promise.resolve({ ok: true, json: async () => ({ ...SUMMARY, totals: null, unpriced_tickers: ["AAPL"] }) }) });
    vi.stubGlobal("fetch", fetchMock);
    renderAt("12");
    expect(await screen.findByText(/prices unavailable/i)).toBeInTheDocument();
  });

  it("clicking Generate report calls generateClientReport and re-fetches the full report on success", async () => {
    let getFullReportCount = 0;
    const fetchMock = fetchRouter({
      report: () => {
        getFullReportCount += 1;
        const generated_reports = getFullReportCount >= 2
          ? [...FULL_REPORT.generated_reports, { filename: "new.xlsx", generated_at: "2026-01-02T00:00:00+00:00", download_url: "/workspace/files/new.xlsx" }]
          : FULL_REPORT.generated_reports;
        return Promise.resolve({ ok: true, json: async () => ({ ...FULL_REPORT, generated_reports }) });
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /view full report/i }));
    await screen.findByText(FULL_REPORT.narrative);
    expect(getFullReportCount).toBe(1);
    await user.click(screen.getByRole("button", { name: /generate report/i }));
    expect(await screen.findByText("new.xlsx")).toBeInTheDocument();
    expect(getFullReportCount).toBe(2);
  });

  it("shows the thrown error message inline when Generate report fails", async () => {
    const fetchMock = fetchRouter({ generate: () => Promise.resolve({ ok: false, status: 502, json: async () => ({ detail: "could not price: AAPL" }) }) });
    vi.stubGlobal("fetch", fetchMock);
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();

    renderAt("12");
    await screen.findByText("Jane Doe");
    await user.click(screen.getByRole("button", { name: /view full report/i }));
    await screen.findByText(FULL_REPORT.narrative);
    await user.click(screen.getByRole("button", { name: /generate report/i }));
    expect(await screen.findByText(/could not price: AAPL/i)).toBeInTheDocument();
  });

  it("shows an error banner with a link back to /reports when the summary fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }));
    renderAt("999");
    expect(await screen.findByRole("alert")).toHaveTextContent(/failed to load/i);
    expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/reports");
  });

  it("always shows a link back to /reports once the summary loads", async () => {
    vi.stubGlobal("fetch", fetchRouter({}));
    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/reports");
  });
});
