import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ClientWithHoldings } from "../lib/api";
import { ReportsList } from "./ReportsList";

const CLIENTS: ClientWithHoldings[] = [{
  client_id: 1,
  name: "Jane Doe",
  email: "jane@x.com",
  segment: "VIP",
  risk_profile: "balanced",
  advisor: "Sam",
  city: "Paris",
  holdings: [{ ticker: "AAPL", shares: 10, avg_cost: 150 }],
}];

function renderList(clients = CLIENTS) {
  return render(
    <MemoryRouter initialEntries={["/reports"]}>
      <Routes>
        <Route path="/reports" element={<ReportsList clients={clients} />} />
        <Route path="/reports/:id" element={<div data-testid="navigated-to">arrived</div>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ReportsList", () => {
  it("renders report-selection cards with client context but no holdings table", () => {
    renderList();

    expect(screen.getByRole("heading", { name: "Choose a client" })).toBeInTheDocument();
    expect(screen.getByText("Jane Doe")).toBeInTheDocument();
    expect(screen.getByText("Balanced risk")).toBeInTheDocument();
    expect(screen.getByText("Advisor Sam")).toBeInTheDocument();
    expect(screen.getByText(/1 holding/)).toBeInTheDocument();
    expect(screen.queryByText("AAPL")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Open report for Jane Doe" })).toBeInTheDocument();
  });

  it("navigates to the selected client report", async () => {
    const user = userEvent.setup();
    renderList();

    await user.click(screen.getByRole("button", { name: "Open report for Jane Doe" }));

    expect(await screen.findByTestId("navigated-to")).toBeInTheDocument();
  });

  it("shows an intentional empty state", () => {
    renderList([]);

    expect(screen.getByText("No report clients yet")).toBeInTheDocument();
  });
});
