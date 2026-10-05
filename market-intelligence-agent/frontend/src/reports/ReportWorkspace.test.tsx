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
  positions: [], unpriced_tickers: [],
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
  it("shows a loading indicator while the summary itself is loading, not a blank page", async () => {
    // Regression (live QA): the page rendered nothing at all (return null)
    // while the summary fetch was in flight -- indistinguishable from a
    // crash or a frozen tab during the several seconds a cold yfinance
    // quote can take.
    let resolveSummary: (v: unknown) => void;
    const summaryPromise = new Promise((resolve) => { resolveSummary = resolve; });
    vi.stubGlobal("fetch", fetchRouter({ summary: () => summaryPromise as Promise<unknown> }));

    renderAt("12");
    expect(await screen.findByText(/loading/i)).toBeInTheDocument();

    resolveSummary!({ ok: true, json: async () => SUMMARY });
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
  });

  it("shows the client summary quickly and a 'View full report' button, without fetching the full report", async () => {
    const fetchMock = fetchRouter({});
    vi.stubGlobal("fetch", fetchMock);
    renderAt("12");
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /view full report/i })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/report") && !String(url).includes("/summary"))).toBe(false);
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
    await user.click(screen.getByRole("button", { name: /view full report/i }));
    expect(await screen.findByText(/loading/i)).toBeInTheDocument();

    resolveReport!({ ok: true, json: async () => FULL_REPORT });
    expect(await screen.findByText(FULL_REPORT.narrative)).toBeInTheDocument();
    expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument(); // SectorAllocationChart
    expect(screen.getAllByText(/Concentration/).length).toBeGreaterThan(0); // section heading + ConcentrationAlert
    expect(screen.getAllByText("AAPL").length).toBeGreaterThan(0);
    expect(screen.getByText("jane-doe-portfolio-brief-2026-01-01.xlsx")).toBeInTheDocument();
    // Each chart section has its own caption -- live QA feedback was "a
    // wall of text, then a wall of unlabeled graphs."
    expect(screen.getByText("Portfolio allocation")).toBeInTheDocument();
    expect(screen.getByText("Sector exposure")).toBeInTheDocument();
    expect(screen.getByText("Positions")).toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: /generate report/i }));
    expect(await screen.findByText("new.xlsx")).toBeInTheDocument();
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
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/reports");
  });

  it("always shows a link back to /reports once the summary loads", async () => {
    vi.stubGlobal("fetch", fetchRouter({}));
    renderAt("12");
    await screen.findByText("Jane Doe");
    expect(screen.getByRole("link", { name: /back/i })).toHaveAttribute("href", "/reports");
  });
});
