import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReportsList } from "./ReportsList";

function renderAt() {
  return render(
    <MemoryRouter initialEntries={["/reports"]}>
      <Routes>
        <Route path="/reports" element={<ReportsList />} />
        <Route path="/reports/:id" element={<div data-testid="navigated-to">arrived</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReportsList", () => {
  it("renders each client's profile (no holdings table)", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 1, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris",
        holdings: [{ ticker: "AAPL", shares: 10, avg_cost: 150 }],
      }],
    }));
    renderAt();
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText(/balanced/)).toBeInTheDocument();
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
  });

  it("shows an error message when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));
    renderAt();
    expect(await screen.findByText(/failed to load clients/i)).toBeInTheDocument();
  });

  it("clicking a client row navigates to /reports/:id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    renderAt();
    await user.click(await screen.findByText("Jane Doe"));
    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });
});
