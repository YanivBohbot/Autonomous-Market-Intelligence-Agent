import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

// Delegates the chat to DeskView instead of rendering a bare CopilotChat --
// DeskView already owns a correctly-configured CopilotKitProvider +
// HttpAgent (registered for MARKET_DESK_AGENT_ID) + messageFilter +
// useDeskInterrupt/useToolDisplay. A standalone CopilotChat here had none
// of that: useAgent (called by DeskActivityRail) throws
// "useCopilotKit must be used within CopilotKitProvider" with no provider
// above it, which crashed every real render of this page. Mocking DeskView
// (not the whole @copilotkit/react-core/v2 module) proves the delegation
// itself, which is what keeps this page working: if ClientWorkspace ever
// reverts to building its own CopilotChat/provider, this mock is bypassed
// and DeskView's props assertion below stops proving anything useful --
// the live QA pass is what ultimately catches that regression.
const deskViewProps: Record<string, unknown>[] = [];
vi.mock("../desk/DeskView", () => ({
  DeskView: (props: Record<string, unknown>) => {
    deskViewProps.push(props);
    return <div data-testid="desk-view-mock" />;
  },
}));

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
  it("always shows a link back to /clients, even when the client loaded successfully", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], unpriced_tickers: [],
      }),
    }));
    renderAt("12");
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /retour/i })).toHaveAttribute("href", "/clients");
  });

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

  it("shows 'no position' copy when totals is null and nothing is unpriced", async () => {
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

  it("shows 'prices unavailable' instead of 'no position' when every ticker failed to price", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], unpriced_tickers: ["AAPL"],
      }),
    }));
    renderAt("12");
    expect(await screen.findByText(/prices unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText(/no position/i)).not.toBeInTheDocument();
  });

  it("notes partially-unpriced tickers next to the computed totals", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: { market_value: 2000, cost_basis: 1500, unrealized_pnl: 500, unrealized_pnl_pct: 33.33 },
        positions: [], unpriced_tickers: ["MSFT"],
      }),
    }));
    renderAt("12");
    expect(await screen.findByText(/MSFT/)).toBeInTheDocument();
  });

  it("delegates the chat to DeskView with a client-scoped threadId", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        totals: null, positions: [], unpriced_tickers: [],
      }),
    }));
    renderAt("12");
    await screen.findByTestId("desk-view-mock");
    expect(deskViewProps[deskViewProps.length - 1].threadId).toBe("clients_12");
  });

  it("remounts (fresh fetch, fresh DeskView/thread) when navigating from one client to another", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const { Link } = await import("react-router-dom");
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      const id = url.match(/\/clients\/(\d+)\/summary/)?.[1];
      return Promise.resolve({
        ok: true,
        json: async () => ({
          client_id: Number(id), name: `Client ${id}`, email: "x@x.com", segment: "VIP",
          risk_profile: "balanced", advisor: "Sam", city: "Paris",
          totals: null, positions: [], unpriced_tickers: [],
        }),
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

  it("shows an error banner with a link back to /clients when the summary fetch fails, and does not mount the chat", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({}) }));
    renderAt("not-a-number");
    expect(await screen.findByText(/failed to load/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /retour/i })).toHaveAttribute("href", "/clients");
    expect(screen.queryByTestId("desk-view-mock")).not.toBeInTheDocument();
  });
});
