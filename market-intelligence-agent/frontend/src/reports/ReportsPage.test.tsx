import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReportsPage } from "./ReportsPage";

describe("ReportsPage", () => {
  it("renders the client list, and a row click navigates to /reports/:id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        client_id: 12, name: "Jane Doe", email: "jane@x.com", segment: "VIP",
        risk_profile: "balanced", advisor: "Sam", city: "Paris", holdings: [],
      }],
    }));
    render(
      <MemoryRouter initialEntries={["/reports"]}>
        <Routes>
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/reports/:id" element={<div data-testid="navigated-to">arrived</div>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    await user.click(screen.getByText("Jane Doe"));
    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });
});
