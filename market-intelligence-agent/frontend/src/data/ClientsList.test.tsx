import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ClientsList } from "./ClientsList";

describe("ClientsList", () => {
  it("renders each client with their holdings", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        holdings: [{ ticker: "AAPL", shares: 10, avg_cost: 150 }],
      }],
    }));
    render(<ClientsList />);
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("AAPL")).toBeInTheDocument();
  });

  it("renders a client with no holdings without crashing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    render(<ClientsList />);
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
  });
});
