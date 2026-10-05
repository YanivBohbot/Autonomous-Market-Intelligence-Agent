import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { BriefingPage } from "./BriefingPage";
import type { BriefingData } from "../lib/api";

const DATA: BriefingData = {
  indices: [{ symbol: "^GSPC", name: "S&P 500", price: 5800.0, change_pct: 0.73 }],
  sectors: [{ symbol: "XLK", name: "Technology", price: 230.0, change_pct: 1.2 }],
  watchlist: [
    { symbol: "AAPL", name: "Apple Inc.", price: 258.0, change_pct: -0.5, points: [{ date: "2026-09-21", close: 258.0 }] },
  ],
  narrative: "Markets edged higher today on strong tech earnings.",
  news: [{ title: "Markets rally", url: "https://example.com/a" }],
  client_alerts: { available: true, threshold_pct: 30.0, breaches: [{ label: "Jane Doe", ticker: "NVDA", weight_pct: 65.0, market_value: 65000 }] },
};

function stubFetch(data: BriefingData) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => data }));
}

describe("BriefingPage", () => {
  it("shows a loading indicator, then renders every section", async () => {
    stubFetch(DATA);
    render(<BriefingPage />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();

    expect(await screen.findByText("S&P 500")).toBeInTheDocument();
    expect(screen.getByText("Technology")).toBeInTheDocument();
    expect(screen.getByText("Apple Inc.")).toBeInTheDocument();
    expect(screen.getByText(/Résumé du marché macro-économique et micro-économique/)).toBeInTheDocument();
    expect(screen.getByText(DATA.narrative)).toBeInTheDocument();
    expect(screen.getByText("Markets rally")).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument(); // via ConcentrationAlert
    expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
  });

  it("shows an error message when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500, json: async () => ({}) }));
    render(<BriefingPage />);
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
  });

  it("omits the indices/sectors/watchlist sections when they are empty", async () => {
    stubFetch({ ...DATA, indices: [], sectors: [], watchlist: [] });
    render(<BriefingPage />);
    await screen.findByText(DATA.narrative);
    expect(screen.queryByText("S&P 500")).not.toBeInTheDocument();
    expect(screen.queryByText("Technology")).not.toBeInTheDocument();
    expect(screen.queryByText("Apple Inc.")).not.toBeInTheDocument();
  });

  it("shows a 'No news available' fallback when news is empty", async () => {
    stubFetch({ ...DATA, news: [] });
    render(<BriefingPage />);
    expect(await screen.findByText(/no news available/i)).toBeInTheDocument();
  });

  it("shows 'No concentration breaches' and does not render ConcentrationAlert when available but empty", async () => {
    // Regression (chantier-3 finding, pinned again here): an empty
    // breaches list must never render an empty alert box.
    stubFetch({ ...DATA, client_alerts: { available: true, threshold_pct: 30.0, breaches: [] } });
    render(<BriefingPage />);
    expect(await screen.findByText(/no concentration breaches/i)).toBeInTheDocument();
    expect(screen.queryByText(/Concentration >/)).not.toBeInTheDocument();
  });

  it("shows an 'Alerts unavailable' fallback when client_alerts.available is false", async () => {
    stubFetch({ ...DATA, client_alerts: { available: false, threshold_pct: 30.0, breaches: [] } });
    render(<BriefingPage />);
    expect(await screen.findByText(/alerts unavailable/i)).toBeInTheDocument();
  });
});
