import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Routes, Route, Navigate } from "react-router-dom";
import { AppLayout } from "./AppLayout";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<AppLayout threadId="t1" onNewSession={() => undefined} />}>
          <Route path="/" element={<Navigate to="/recherche" replace />} />
          <Route path="/briefing" element={<div>briefing page</div>} />
          <Route path="/clients" element={<div>clients page</div>} />
          <Route path="/recherche" element={<div>recherche page</div>} />
          <Route path="/rapports" element={<div>rapports page</div>} />
          <Route path="/data" element={<div>data page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

describe("AppLayout", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "ok", version: "1.2.3" }) }),
    );
  });

  it("shows all 5 nav links with the right labels and hrefs", () => {
    renderAt("/recherche");
    expect(screen.getByRole("link", { name: "Briefing" })).toHaveAttribute("href", "/briefing");
    expect(screen.getByRole("link", { name: "Clients" })).toHaveAttribute("href", "/clients");
    expect(screen.getByRole("link", { name: "Recherche" })).toHaveAttribute("href", "/recherche");
    expect(screen.getByRole("link", { name: "Rapports" })).toHaveAttribute("href", "/rapports");
    expect(screen.getByRole("link", { name: "Données" })).toHaveAttribute("href", "/data");
  });

  it("has no nav link to /classic", () => {
    renderAt("/recherche");
    expect(screen.queryByRole("link", { name: /classic/i })).not.toBeInTheDocument();
  });

  it("marks the active route's nav link and not the others", () => {
    renderAt("/rapports");
    expect(screen.getByRole("link", { name: "Rapports" })).toHaveClass("text-terminal-accent");
    expect(screen.getByRole("link", { name: "Recherche" })).not.toHaveClass("text-terminal-accent");
  });

  it("redirects / to /recherche", () => {
    renderAt("/");
    expect(screen.getByText("recherche page")).toBeInTheDocument();
  });

  it("toggling the theme button updates the document's data-theme attribute", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/recherche");
    document.documentElement.setAttribute("data-theme", "light");
    await user.click(screen.getByRole("button", { name: /dark/i }));
    expect(document.documentElement.getAttribute("data-theme")).toBe("dark");
  });

  it("shows the session id and calls onNewSession when + New session is clicked, even on a non-chat route", async () => {
    const onNewSession = vi.fn();
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/data"]}>
        <Routes>
          <Route element={<AppLayout threadId="t1" onNewSession={onNewSession} />}>
            <Route path="/data" element={<div>data page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByText("t1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(onNewSession).toHaveBeenCalledOnce();
  });
});
