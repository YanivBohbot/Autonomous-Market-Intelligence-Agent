import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ReportsPage } from "./ReportsPage";

const CLIENT = {
  client_id: 12,
  name: "Jane Doe",
  email: "jane@x.com",
  segment: "VIP",
  risk_profile: "balanced",
  advisor: "Sam",
  city: "Paris",
  holdings: [{ ticker: "AAPL", shares: 10, avg_cost: 150 }],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/reports"]}>
      <Routes>
        <Route path="/reports" element={<ReportsPage />} />
        <Route path="/reports/:id" element={<div data-testid="navigated-to">arrived</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReportsPage", () => {
  it("shows a report-directory skeleton while clients load", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

    renderPage();

    expect(screen.getByRole("heading", { name: "Reports" })).toBeInTheDocument();
    expect(screen.getAllByRole("status", { name: "Loading report metric" })).toHaveLength(4);
    expect(screen.getByRole("status", { name: "Loading report directory" })).toBeInTheDocument();
  });

  it("renders shared overview metrics and opens a structured report-selection card", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [CLIENT] }));

    renderPage();

    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("Report-ready clients")).toBeInTheDocument();
    expect(screen.getByText("Holding rows")).toBeInTheDocument();
    expect(screen.getByText("Segments")).toBeInTheDocument();
    expect(screen.getByText("Advisors")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Open report for Jane Doe" }));
    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });

  it("shows a retryable shared error state and recovers", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => [CLIENT] });
    vi.stubGlobal("fetch", fetchMock);

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Reports unavailable");
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("Jane Doe")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
