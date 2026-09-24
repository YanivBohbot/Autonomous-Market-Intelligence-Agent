import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// CopilotKit needs a real browser + backend; the desk shell is covered by the
// live pass. Here we only check that App switches between the two layouts.
vi.mock("./desk/DeskView", () => ({
  DeskView: ({ threadId }: { threadId: string }) => <div data-testid="desk-view">{threadId}</div>,
}));

import App from "./App";

describe("App", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok", version: "1.2.3" }),
    }));
  });

  it("opens in Market Desk mode by default", () => {
    render(<App />);
    expect(screen.getByTestId("desk-view")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/ask the agent/i)).not.toBeInTheDocument();
  });

  it("switches to Classic, shows the classic chat, and remembers it", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<App />);
    await user.click(screen.getByRole("button", { name: "Classic" }));
    expect(screen.getByText(/MIA · Dev Console/)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
    expect(screen.queryByTestId("desk-view")).not.toBeInTheDocument();
    unmount();

    render(<App />);
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
  });

  it("New session gives the desk a new thread id", async () => {
    const user = userEvent.setup();
    render(<App />);
    const before = screen.getByTestId("desk-view").textContent;
    await user.click(screen.getByRole("button", { name: /new session/i }));
    expect(screen.getByTestId("desk-view").textContent).not.toBe(before);
  });
});
