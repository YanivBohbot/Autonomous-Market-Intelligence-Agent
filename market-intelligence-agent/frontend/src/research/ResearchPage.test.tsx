import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";

vi.mock("../desk/DeskView", () => ({
  DeskView: ({ threadId }: { threadId: string }) => <div data-testid="desk">{threadId}</div>,
}));
vi.mock("./ConversationPanel", () => ({
  ConversationPanel: (p: { onSelect(id: string): void; onNew(): void; onDeleted(id: string): void; activeId: string }) => (
    <div>
      <button onClick={() => p.onSelect("desk_b")}>pick b</button>
      <button onClick={p.onNew}>new</button>
      <button onClick={() => p.onDeleted(p.activeId)}>delete active</button>
      <button onClick={() => p.onDeleted("desk_other")}>delete other</button>
    </div>
  ),
}));

import { ResearchPage } from "./ResearchPage";

function Loc() {
  return <div data-testid="loc">{useLocation().search}</div>;
}
function renderAt(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes><Route path="/research" element={<><ResearchPage /><Loc /></>} /></Routes>
    </MemoryRouter>,
  );
}

describe("ResearchPage", () => {
  it("opens the conversation named in ?c", () => {
    renderAt("/research?c=desk_a");
    expect(screen.getByTestId("desk")).toHaveTextContent("desk_a");
  });

  it("creates a desk_ id when ?c is missing and writes it to the URL", () => {
    renderAt("/research");
    const id = screen.getByTestId("desk").textContent!;
    expect(id).toMatch(/^desk_/);
    expect(screen.getByTestId("loc")).toHaveTextContent(`?c=${id}`);
  });

  it("ignores a non-desk c param", () => {
    renderAt("/research?c=clients_17");
    expect(screen.getByTestId("desk").textContent).toMatch(/^desk_/);
    expect(screen.getByTestId("desk").textContent).not.toBe("clients_17");
  });

  it("switches and starts new conversations", async () => {
    renderAt("/research?c=desk_a");
    await userEvent.click(screen.getByText("pick b"));
    expect(screen.getByTestId("desk")).toHaveTextContent("desk_b");
    await userEvent.click(screen.getByText("new"));
    expect(screen.getByTestId("desk").textContent).not.toBe("desk_b");
  });

  it("deleting the active conversation opens a new one; deleting another keeps it", async () => {
    renderAt("/research?c=desk_a");
    await userEvent.click(screen.getByText("delete other"));
    expect(screen.getByTestId("desk")).toHaveTextContent("desk_a");
    await userEvent.click(screen.getByText("delete active"));
    expect(screen.getByTestId("desk").textContent).not.toBe("desk_a");
  });
});
