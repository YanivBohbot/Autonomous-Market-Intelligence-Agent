import { useState } from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ClientWithHoldings } from "../lib/api";
import { ClientsList } from "./ClientsList";

const CLIENTS: ClientWithHoldings[] = [
  {
    client_id: 1, name: "Jane Doe", email: "jane@example.com", segment: "VIP",
    risk_profile: "balanced", advisor: "Sam", city: "Paris",
    holdings: [
      { ticker: "AAPL", shares: 10, avg_cost: 150 },
      { ticker: "NVDA", shares: 5, avg_cost: 90 },
      { ticker: "BTC-USD", shares: 1, avg_cost: 50_000 },
      { ticker: "TSLA", shares: 2, avg_cost: 200 },
      { ticker: "GLD", shares: 4, avg_cost: 180 },
    ],
  },
  {
    client_id: 2, name: "Alex Smith", email: "alex@example.com", segment: "Private",
    risk_profile: "aggressive", advisor: "Maya", city: "London",
    holdings: [{ ticker: "MSFT", shares: 8, avg_cost: 300 }],
  },
  {
    client_id: 3, name: "Sam Lee", email: "sam@example.com", segment: "VIP",
    risk_profile: "balanced", advisor: "Maya", city: "Singapore", holdings: [],
  },
];

function StatefulList({ clients = CLIENTS }: { clients?: ClientWithHoldings[] }) {
  const [query, setQuery] = useState("");
  const [segment, setSegment] = useState("all");
  const [riskProfile, setRiskProfile] = useState("all");
  return (
    <ClientsList
      clients={clients}
      query={query}
      segment={segment}
      riskProfile={riskProfile}
      onQueryChange={setQuery}
      onSegmentChange={setSegment}
      onRiskProfileChange={setRiskProfile}
      onClearFilters={() => { setQuery(""); setSegment("all"); setRiskProfile("all"); }}
    />
  );
}

function renderList(clients = CLIENTS) {
  return render(<MemoryRouter><StatefulList clients={clients} /></MemoryRouter>);
}

describe("ClientsList", () => {
  it("searches locally by name, email, and ticker", async () => {
    const user = userEvent.setup();
    renderList();
    const search = screen.getByRole("searchbox", { name: "Search clients" });

    await user.type(search, "jane");
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.queryByText("Alex Smith")).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "alex@example.com");
    expect(screen.getByText("Alex Smith")).toBeInTheDocument();
    expect(screen.queryByText("Jane Doe")).not.toBeInTheDocument();

    await user.clear(search);
    await user.type(search, "AAPL");
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.queryByText("Alex Smith")).not.toBeInTheDocument();
  });

  it("combines segment and risk filters and clears them", async () => {
    const user = userEvent.setup();
    renderList();

    await user.selectOptions(screen.getByLabelText("Segment"), "VIP");
    await user.selectOptions(screen.getByLabelText("Risk profile"), "aggressive");
    expect(screen.getByText("No clients match your filters")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("Alex Smith")).toBeInTheDocument();
    expect(screen.getByText("Sam Lee")).toBeInTheDocument();
  });

  it("caps each holding preview at three and shows the overflow count", () => {
    renderList();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
    expect(screen.getByText("BTC-USD")).toBeInTheDocument();
    expect(screen.queryByText("TSLA")).not.toBeInTheDocument();
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("shows an explanatory empty state for an empty client collection", () => {
    renderList([]);
    expect(screen.getByText("No clients yet")).toBeInTheDocument();
  });

  it("navigates to /clients/:id from a client card", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/clients"]}>
        <Routes>
          <Route path="/clients" element={<StatefulList />} />
          <Route path="/clients/:id" element={<div data-testid="navigated-to">arrived</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await user.click(screen.getByRole("button", { name: "Open client Jane Doe" }));
    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });
});
