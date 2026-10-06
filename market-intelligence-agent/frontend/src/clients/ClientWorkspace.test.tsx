import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";

const deskViewProps: Record<string, unknown>[] = [];
vi.mock("../desk/DeskView", () => ({
  DeskView: (props: Record<string, unknown>) => {
    deskViewProps.push(props);
    return <div data-testid="desk-view-mock" />;
  },
}));

import type { ClientSummary } from "../lib/api";
import { ClientWorkspace } from "./ClientWorkspace";

const clientSummary = (overrides: Partial<ClientSummary> = {}): ClientSummary => ({
  client_id: 12,
  name: "Jane Doe",
  email: "jane@x.com",
  segment: "VIP",
  risk_profile: "balanced",
  advisor: "Sam",
  city: "Paris",
  totals: null,
  positions: [],
  unpriced_tickers: [],
  ...overrides,
});

function respondWith(summary: ClientSummary) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    json: async () => summary,
  }));
}

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
  beforeEach(() => {
    deskViewProps.length = 0;
  });

  it("shows a structured client workspace skeleton while the summary loads", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

    renderAt("12");

    expect(screen.getByRole("status", { name: "Loading client profile" })).toBeInTheDocument();
    expect(screen.getAllByRole("status", { name: "Loading client metric" })).toHaveLength(4);
    expect(screen.queryByTestId("desk-view-mock")).not.toBeInTheDocument();
  });

  it("renders the client hero, badges, and four portfolio KPIs", async () => {
    respondWith(clientSummary({
      totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
      positions: [
        { ticker: "AAPL", shares: 5, avg_cost: 300, price: 400, market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33, weight_pct: 100, sector: "Technology" },
      ],
    }));

    renderAt("12");

    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(screen.getByText("VIP")).toBeInTheDocument();
    expect(screen.getByText("Balanced risk")).toHaveAttribute("data-tone", "info");
    expect(screen.getByText("Advisor Sam")).toHaveAttribute("data-tone", "neutral");
    expect(screen.getByText("Market value")).toBeInTheDocument();
    expect(screen.getByText("$2,000.00")).toBeInTheDocument();
    expect(screen.getByText("Unrealized P&L")).toBeInTheDocument();
    expect(screen.getByText("+$500.00")).toBeInTheDocument();
    expect(screen.getByText("Return")).toBeInTheDocument();
    expect(screen.getByText("+33.3%")).toBeInTheDocument();
    expect(screen.getByText("Priced positions")).toBeInTheDocument();
    expect(screen.getByText("1 of 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to clients/i })).toHaveAttribute("href", "/clients");
  });

  it("shows no-position copy when the portfolio is empty", async () => {
    respondWith(clientSummary());

    renderAt("12");

    expect(await screen.findByText("No positions")).toBeInTheDocument();
  });

  it("shows pricing-unavailable copy when every ticker failed to price", async () => {
    respondWith(clientSummary({ unpriced_tickers: ["AAPL"] }));

    renderAt("12");

    expect(await screen.findByText("Pricing unavailable")).toBeInTheDocument();
    expect(screen.getByText("AAPL could not be priced")).toBeInTheDocument();
    expect(screen.queryByText("No positions")).not.toBeInTheDocument();
  });

  it("makes partial pricing explicit next to the portfolio metrics", async () => {
    respondWith(clientSummary({
      totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
      positions: [
        { ticker: "AAPL", shares: 5, avg_cost: 300, price: 400, market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33, weight_pct: 100, sector: "Technology" },
      ],
      unpriced_tickers: ["MSFT"],
    }));

    renderAt("12");

    expect(await screen.findByText("1 of 2")).toBeInTheDocument();
    expect(screen.getByText("Totals exclude MSFT")).toBeInTheDocument();
  });

  it("delegates the chat to DeskView with the exact client-scoped threadId", async () => {
    respondWith(clientSummary());

    renderAt("12");

    await screen.findByTestId("desk-view-mock");
    expect(deskViewProps[deskViewProps.length - 1].threadId).toBe("clients_12");
  });

  it("remounts with a fresh fetch and thread when navigating between clients", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const id = String(input).match(/\/clients\/(\d+)\/summary/)?.[1];
      return Promise.resolve({
        ok: true,
        json: async () => clientSummary({ client_id: Number(id), name: `Client ${id}` }),
      });
    }));
    render(
      <MemoryRouter initialEntries={["/clients/12"]}>
        <Routes>
          <Route path="/clients/:id" element={<><Link to="/clients/13">go to 13</Link><ClientWorkspace /></>} />
        </Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByText("Client 12")).toBeInTheDocument();
    await user.click(screen.getByText("go to 13"));

    expect(await screen.findByText("Client 13")).toBeInTheDocument();
    expect(screen.queryByText("Client 12")).not.toBeInTheDocument();
    expect(deskViewProps[deskViewProps.length - 1].threadId).toBe("clients_13");
  });

  it("offers retry and back navigation after a summary error, then recovers", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => clientSummary() });
    vi.stubGlobal("fetch", fetchMock);

    renderAt("12");

    expect(await screen.findByRole("alert")).toHaveTextContent("Client workspace unavailable");
    expect(screen.getByRole("link", { name: /back to clients/i })).toHaveAttribute("href", "/clients");
    expect(screen.queryByTestId("desk-view-mock")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByRole("heading", { name: "Jane Doe" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("desk-view-mock")).toBeInTheDocument();
  });
});
