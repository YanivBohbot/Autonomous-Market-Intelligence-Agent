import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("./desk/DeskView", () => ({
  DeskView: ({ threadId }: { threadId: string }) => <div data-testid="desk-view">{threadId}</div>,
}));
vi.mock("./clients/ClientWorkspace", () => ({
  ClientWorkspace: () => <div data-testid="client-workspace" />,
}));

import App from "./App";

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}>{<App />}</MemoryRouter>);
}

describe("App routing", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: "ok", version: "1.2.3" }),
      }),
    );
  });

  it("/ redirects to /recherche", () => {
    renderAt("/");
    expect(screen.getByTestId("desk-view")).toBeInTheDocument();
  });

  it("/recherche renders Market Desk", () => {
    renderAt("/recherche");
    expect(screen.getByTestId("desk-view")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/ask the agent/i)).not.toBeInTheDocument();
  });

  it("/classic renders the classic chat", () => {
    renderAt("/classic");
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
    expect(screen.queryByTestId("desk-view")).not.toBeInTheDocument();
  });

  it("/classic has no AppLayout nav (it's outside the layout)", () => {
    renderAt("/classic");
    expect(screen.queryByRole("link", { name: "Recherche" })).not.toBeInTheDocument();
  });

  it("the two not-yet-built sections render ComingSoonPage without crashing", () => {
    for (const path of ["/briefing", "/rapports"]) {
      const { unmount } = renderAt(path);
      expect(screen.getByText(/bientôt disponible/i)).toBeInTheDocument();
      unmount();
    }
  });

  it("/clients renders the client list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/data/clients") {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => ({ status: "ok", version: "1.2.3" }) });
      }),
    );
    renderAt("/clients");
    expect(screen.queryByTestId("client-workspace")).not.toBeInTheDocument();
  });

  it("/clients/:id renders the client workspace", () => {
    renderAt("/clients/12");
    expect(screen.getByTestId("client-workspace")).toBeInTheDocument();
  });

  it("New session gives the desk a new thread id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/recherche");
    const before = screen.getByTestId("desk-view").textContent;
    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(screen.getByTestId("desk-view").textContent).not.toBe(before);
  });

  it("Market Desk runs on its own thread, never Classic's", () => {
    const classic = renderAt("/classic");
    const classicThread = screen.getByText(/^web_session_/).textContent;
    classic.unmount();
    renderAt("/recherche");
    expect(screen.getByTestId("desk-view").textContent).not.toBe(classicThread);
  });

  it("New session clears Classic's chat history", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/classic");

    await user.type(screen.getByPlaceholderText(/ask the agent/i), "hello world");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("hello world")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(screen.queryByText("hello world")).not.toBeInTheDocument();
  });
});
