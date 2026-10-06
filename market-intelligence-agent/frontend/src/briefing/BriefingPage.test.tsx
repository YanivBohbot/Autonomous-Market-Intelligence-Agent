import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BriefingPage } from "./BriefingPage";

const pageHeaderProps = vi.hoisted(() => [] as Array<{
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children?: React.ReactNode;
}>);

vi.mock("../ui/PageHeader", () => ({
  PageHeader: (props: (typeof pageHeaderProps)[number]) => {
    pageHeaderProps.push(props);
    return (
      <header data-testid="page-header">
        <p>{props.eyebrow}</p>
        <h1>{props.title}</h1>
        <p>{props.description}</p>
        <div>{props.actions}</div>
        <div>{props.children}</div>
      </header>
    );
  },
}));

vi.mock("./MarketIndexGrid", () => ({ MarketIndexGrid: ({ market }: { market: { id: string } }) => <div data-testid="indices">indices:{market.id}</div> }));
vi.mock("./MarketSummary", () => ({ MarketSummary: ({ market }: { market: string }) => <div data-testid="summary">summary:{market}</div> }));
vi.mock("./MarketNews", () => ({ MarketNews: ({ market }: { market: string }) => <div data-testid="news">news:{market}</div> }));
vi.mock("./MarketMovers", () => ({ MarketMovers: ({ market }: { market: string }) => <div data-testid="movers">movers:{market}</div> }));
vi.mock("./SectorPanel", () => ({ SectorPanel: () => <div>sectors</div> }));
vi.mock("./WatchlistGrid", () => ({ WatchlistGrid: () => <div>watchlist</div> }));
vi.mock("./ClientAlertsPanel", () => ({ ClientAlertsPanel: () => <div>alerts</div> }));
vi.mock("./briefingData", () => ({ loadMarketIndices: vi.fn(() => Promise.resolve([])), prefetchMarket: vi.fn() }));

describe("BriefingPage", () => {
  beforeEach(() => {
    pageHeaderProps.length = 0;
  });

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

  it("passes the market identity, live status, and tabs through PageHeader", () => {
    render(<BriefingPage />);

    expect(pageHeaderProps).toHaveLength(1);
    expect(pageHeaderProps[0]).toMatchObject({
      eyebrow: "Market intelligence",
      title: "Global markets briefing",
      description: expect.stringMatching(/refreshed independently/i),
    });
    expect(screen.getByTestId("page-header")).toHaveTextContent("Live data");
    expect(screen.getByTestId("page-header")).toContainElement(screen.getByRole("button", { name: "U.S." }));
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
    expect(screen.getByText("alerts")).toBeInTheDocument();
  });

  it("offers the six requested market tabs", () => {
    render(<BriefingPage />);
    for (const name of ["U.S.", "Europe", "Asia", "Latin America", "Currencies", "Crypto"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });
});
