import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ClientsPage } from "./ClientsPage";

describe("ClientsPage", () => {
  it("renders the client list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    render(<MemoryRouter><ClientsPage /></MemoryRouter>);
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
  });
});
