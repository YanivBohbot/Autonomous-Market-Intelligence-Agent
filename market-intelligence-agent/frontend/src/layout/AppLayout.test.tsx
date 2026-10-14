import { describe, it, expect, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter, Routes, Route, Navigate } from "react-router-dom";

vi.mock("../lib/api", () => ({
  getHealth: vi.fn(() => new Promise(() => undefined)),
}));
vi.mock("./GlobalMarketTicker", () => ({
  GlobalMarketTicker: () => <div data-testid="global-market-ticker">world markets</div>,
}));

import { AppLayout } from "./AppLayout";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppLayout />}>
          <Route path="/" element={<Navigate to="/research" replace />} />
          <Route path="/briefing" element={<div>briefing page</div>} />
          <Route path="/clients" element={<div>clients page</div>} />
          <Route path="/research" element={<div>research page</div>} />
          <Route path="/reports" element={<div>reports page</div>} />
          <Route path="/data" element={<div>data page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppLayout", () => {
  it("launches the Multi-Agent Finance Desk brand without developer branding or version", () => {
    renderAt("/research");
    expect(screen.getByText("MF")).toBeInTheDocument();
    expect(screen.getByText("Multi-Agent Finance Desk")).toBeInTheDocument();
    expect(screen.queryByText(/MIA/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Dev Console/i)).not.toBeInTheDocument();
    expect(screen.queryByText("v1.2.3")).not.toBeInTheDocument();
  });

  it("shows all 5 nav links with their routes and icons", () => {
    renderAt("/research");
    const routes = { Briefing: "/briefing", Clients: "/clients", Research: "/research", Reports: "/reports", Data: "/data" };
    for (const [label, href] of Object.entries(routes)) {
      const link = screen.getByRole("link", { name: label });
      expect(link).toHaveAttribute("href", href);
      expect(link.querySelector("svg")).toBeInTheDocument();
    }
  });

  it("has no nav link to /classic", () => {
    renderAt("/research");
    expect(screen.queryByRole("link", { name: /classic/i })).not.toBeInTheDocument();
  });

  it("marks the active route's nav link and not the others", () => {
    renderAt("/reports");
    expect(screen.getByRole("link", { name: "Reports" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Research" })).not.toHaveAttribute("aria-current");
  });

  it("redirects / to /research", () => {
    renderAt("/");
    expect(screen.getByText("research page")).toBeInTheDocument();
  });

  it("renders the independent ticker without blocking routed content", () => {
    renderAt("/briefing");
    expect(screen.getByTestId("global-market-ticker")).toBeInTheDocument();
    expect(screen.getByText("briefing page")).toBeInTheDocument();
  });

  it("toggling the theme button updates the document's data-theme attribute", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/research");
    document.documentElement.setAttribute("data-theme", "light");
    await user.click(screen.getByRole("button", { name: /dark/i }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("opens the profile preview from the header", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/research");

    await user.click(screen.getByRole("button", { name: "Profile" }));

    expect(screen.getByRole("dialog", { name: "Profile" })).toBeInTheDocument();
    expect(screen.getByText("Desk Operator")).toBeInTheDocument();
  });

  it("opens and closes the mobile navigation and activity rails", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/research");

    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(screen.getByRole("dialog", { name: "Navigation" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close Navigation" }));
    expect(screen.queryByRole("dialog", { name: "Navigation" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open activity" }));
    const activity = screen.getByRole("dialog", { name: "Agent activity" });
    expect(within(activity).getByText("System ready")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Close Agent activity" }));
    expect(screen.queryByRole("dialog", { name: "Agent activity" })).not.toBeInTheDocument();
  });

  it("keeps exactly one activity target with a helpful empty state", () => {
    renderAt("/data");
    expect(screen.getAllByTestId("intelligence-slot")).toHaveLength(1);
    expect(screen.getByText("System ready")).toBeInTheDocument();
    expect(screen.getByText(/activity will appear after/i)).toBeInTheDocument();
  });

  it("no longer shows a session box or a New session button", () => {
    renderAt("/data");
    expect(screen.queryByRole("button", { name: /new session/i })).not.toBeInTheDocument();
    expect(screen.queryByText("Session")).not.toBeInTheDocument();
  });
});
