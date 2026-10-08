import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("./desk/DeskView", () => ({
  DeskView: ({ threadId }: { threadId: string }) => <div data-testid="desk-view">{threadId}</div>,
}));
vi.mock("./clients/ClientWorkspace", () => ({
  ClientWorkspace: () => <div data-testid="client-workspace" />,
}));
vi.mock("./reports/ReportWorkspace", () => ({
  ReportWorkspace: () => <div data-testid="report-workspace" />,
}));
vi.mock("./briefing/BriefingPage", () => ({
  BriefingPage: () => <div data-testid="briefing-page" />,
}));
vi.mock("./layout/GlobalMarketTicker", () => ({
  GlobalMarketTicker: () => <div data-testid="global-market-ticker" />,
}));
vi.mock("./lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./lib/api")>();
  return { ...actual, getHealth: vi.fn(() => new Promise(() => undefined)) };
});

import App from "./App";

function renderAt(path: string) {
  return render(<MemoryRouter initialEntries={[path]}>{<App />}</MemoryRouter>);
}

describe("App routing", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn((request: RequestInfo | URL) => {
        const url = String(request);
        if (url.endsWith("/data/clients") || url.endsWith("/data/documents")) {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => ({ status: "ok", version: "1.2.3" }) });
      }),
    );
  });

  it.each([
    { path: "/briefing", testId: "briefing-page", heading: undefined, settledText: undefined },
    { path: "/clients", testId: undefined, heading: "Clients", settledText: "No clients yet" },
    { path: "/research", testId: "desk-view", heading: undefined, settledText: undefined },
    { path: "/reports", testId: undefined, heading: "Reports", settledText: "No report clients yet" },
    { path: "/data", testId: undefined, heading: "Data", settledText: "No documents ingested yet" },
  ])("keeps the shared product shell visible on $path", async ({ path, testId, heading, settledText }) => {
    renderAt(path);

    expect(screen.getByText("Multi-Agent Finance Desk")).toBeInTheDocument();
    expect(screen.getByTestId("global-market-ticker")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
    for (const label of ["Briefing", "Clients", "Research", "Reports", "Data"]) {
      expect(screen.getByRole("link", { name: label })).toBeInTheDocument();
    }
    if (testId) expect(screen.getByTestId(testId)).toBeInTheDocument();
    if (heading) expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    if (settledText) expect(await screen.findByText(settledText)).toBeInTheDocument();
  });

  it("/ redirects to /research", () => {
    renderAt("/");
    expect(screen.getByTestId("desk-view")).toBeInTheDocument();
  });

  it("/research renders Market Desk", () => {
    renderAt("/research");
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
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
    expect(screen.queryByText("Multi-Agent Finance Desk")).not.toBeInTheDocument();
    expect(screen.queryByTestId("global-market-ticker")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Research" })).not.toBeInTheDocument();
  });

  it("/briefing renders BriefingPage", () => {
    renderAt("/briefing");
    expect(screen.getByTestId("briefing-page")).toBeInTheDocument();
  });

  it("/reports renders the report client list", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url === "/data/clients") {
          return Promise.resolve({ ok: true, json: async () => [] });
        }
        return Promise.resolve({ ok: true, json: async () => ({ status: "ok", version: "1.2.3" }) });
      }),
    );
    renderAt("/reports");
    expect(screen.queryByTestId("report-workspace")).not.toBeInTheDocument();
    expect(await screen.findByText("No report clients yet")).toBeInTheDocument();
  });

  it("/reports/:id renders the report workspace", () => {
    renderAt("/reports/12");
    expect(screen.getByTestId("report-workspace")).toBeInTheDocument();
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
    expect(await screen.findByText("No clients yet")).toBeInTheDocument();
  });

  it("/clients/:id renders the client workspace", () => {
    renderAt("/clients/12");
    expect(screen.getByTestId("client-workspace")).toBeInTheDocument();
  });

  it("New session gives the desk a new thread id", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const user = userEvent.setup();
    renderAt("/research");
    const before = screen.getByTestId("desk-view").textContent;
    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(screen.getByTestId("desk-view").textContent).not.toBe(before);
  });

  it("Market Desk runs on its own thread, never Classic's", () => {
    const classic = renderAt("/classic");
    const classicThread = screen.getByText(/^web_session_/).textContent;
    classic.unmount();
    renderAt("/research");
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
