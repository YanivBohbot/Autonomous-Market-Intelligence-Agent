import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BriefingPage } from "./BriefingPage";

vi.mock("./MarketIndexGrid", () => ({ MarketIndexGrid: ({ market }: { market: { id: string } }) => <div data-testid="indices">indices:{market.id}</div> }));
vi.mock("./MarketSummary", () => ({ MarketSummary: ({ market }: { market: string }) => <div data-testid="summary">summary:{market}</div> }));
vi.mock("./MarketNews", () => ({ MarketNews: ({ market }: { market: string }) => <div data-testid="news">news:{market}</div> }));
vi.mock("./MarketMovers", () => ({ MarketMovers: ({ market }: { market: string }) => <div data-testid="movers">movers:{market}</div> }));
vi.mock("./SectorPanel", () => ({ SectorPanel: () => <div>sectors</div> }));
vi.mock("./WatchlistGrid", () => ({ WatchlistGrid: () => <div>watchlist</div> }));
vi.mock("./ClientAlertsPanel", () => ({ ClientAlertsPanel: () => <div>alerts</div> }));
vi.mock("./briefingData", () => ({ loadMarketIndices: vi.fn(() => Promise.resolve([])), prefetchMarket: vi.fn() }));

describe("BriefingPage", () => {
  it("mounts every independent dashboard component immediately", () => {
    render(<BriefingPage />);
    expect(screen.getByRole("heading", { name: "Global markets briefing" })).toBeInTheDocument();
    expect(screen.getByTestId("indices")).toHaveTextContent("indices:us");
    expect(screen.getByTestId("summary")).toHaveTextContent("summary:us");
    expect(screen.getByTestId("news")).toHaveTextContent("news:us");
    expect(screen.getByTestId("movers")).toHaveTextContent("movers:us");
    expect(screen.getByText("sectors")).toBeInTheDocument();
    expect(screen.getByText("watchlist")).toBeInTheDocument();
    expect(screen.getByText("alerts")).toBeInTheDocument();
  });

  it("changes only market-dependent component props when a tab is clicked", () => {
    render(<BriefingPage />);
    fireEvent.click(screen.getByRole("button", { name: "Europe" }));
    expect(screen.getByTestId("indices")).toHaveTextContent("indices:europe");
    expect(screen.getByTestId("summary")).toHaveTextContent("summary:europe");
    expect(screen.getByTestId("news")).toHaveTextContent("news:europe");
    expect(screen.getByTestId("movers")).toHaveTextContent("movers:europe");
    expect(screen.getByText("sectors")).toBeInTheDocument();
    expect(screen.getByText("watchlist")).toBeInTheDocument();
  });

  it("offers the six requested market tabs", () => {
    render(<BriefingPage />);
    for (const name of ["U.S.", "Europe", "Asia", "Latin America", "Currencies", "Crypto"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });
});
