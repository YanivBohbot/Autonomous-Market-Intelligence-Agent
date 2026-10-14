import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

vi.mock("./desk/DeskView", () => ({
  DeskView: ({ threadId, voiceEnabled }: { threadId: string; voiceEnabled?: boolean }) => (
    <div data-testid="desk-view" data-voice-enabled={String(Boolean(voiceEnabled))}>
      {threadId}
    </div>
  ),
}));
vi.mock("./research/ConversationPanel", () => ({
  ConversationPanel: () => null,
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
    expect(screen.getByTestId("desk-view")).toHaveAttribute("data-voice-enabled", "true");
    expect(screen.queryByPlaceholderText(/ask the agent/i)).not.toBeInTheDocument();
  });

  it("no longer serves the classic chat at /classic", () => {
    renderAt("/classic");
    expect(screen.queryByPlaceholderText("Ask the agent…")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Toggle voice")).not.toBeInTheDocument();
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

  it("/research opens a desk_ conversation through the Research page", () => {
    renderAt("/research");
    expect(screen.getByTestId("desk-view").textContent).toMatch(/^desk_/);
    expect(screen.queryByRole("button", { name: /new session/i })).not.toBeInTheDocument();
  });
});
