import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import type { ClientWithHoldings } from "../lib/api";
import { ClientsPage } from "./ClientsPage";

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

afterEach(() => {
  vi.unstubAllGlobals();
});

function metric(label: string) {
  const card = screen.getByText(label, { selector: "p" }).closest("article");
  if (!card) throw new Error(`Missing metric card ${label}`);
  return within(card);
}

describe("ClientsPage", () => {
  it("loads once and derives four overview metrics from the same response", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => CLIENTS });
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><ClientsPage /></MemoryRouter>);

    expect(screen.getByRole("heading", { name: "Clients" })).toBeInTheDocument();
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(metric("Clients").getByText("3")).toBeInTheDocument();
    expect(metric("Holding rows").getByText("6")).toBeInTheDocument();
    expect(metric("Segments").getByText("2")).toBeInTheDocument();
    expect(metric("Risk distribution").getByText("Balanced 2 · Aggressive 1")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith("/data/clients");
  });
});
