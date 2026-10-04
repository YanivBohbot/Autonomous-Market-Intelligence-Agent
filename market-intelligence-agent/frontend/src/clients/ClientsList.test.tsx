import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ClientsList } from "./ClientsList";

function renderWithRouter() {
  return render(<MemoryRouter><ClientsList /></MemoryRouter>);
}

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
    renderWithRouter();
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
    renderWithRouter();
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
  });

  it("shows an error message when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    renderWithRouter();
    expect(await screen.findByText(/failed to load clients/i)).toBeInTheDocument();
  });

  it("clicking a client row navigates to /clients/:id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const { Route, Routes } = await import("react-router-dom");
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    render(
      <MemoryRouter initialEntries={["/clients"]}>
        <Routes>
          <Route path="/clients" element={<ClientsList />} />
          <Route path="/clients/:id" element={<div data-testid="navigated-to">arrived</div>} />
        </Routes>
      </MemoryRouter>,
    );
    await user.click(await screen.findByText("Jane Doe"));
    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });
});
