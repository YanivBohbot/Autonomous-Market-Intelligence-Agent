import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConversationPanel } from "./ConversationPanel";
import * as api from "./conversationsApi";

vi.mock("./conversationsApi");
const rows = [
  { id: "desk_a", title: "NVDA vs AMD", created_at: "2026-10-14T10:00:00Z", updated_at: "2026-10-14T10:00:00Z" },
  { id: "desk_b", title: "Cohen review", created_at: "2026-10-13T10:00:00Z", updated_at: "2026-10-13T10:00:00Z" },
];

function setup(activeId = "desk_a") {
  const props = { activeId, refreshKey: 0, onSelect: vi.fn(), onNew: vi.fn(), onDeleted: vi.fn() };
  render(<ConversationPanel {...props} />);
  return props;
}

describe("ConversationPanel", () => {
  beforeEach(() => {
    vi.mocked(api.listConversations).mockResolvedValue(rows);
    vi.mocked(api.renameConversation).mockImplementation(async (id, title) => ({ ...rows[0], id, title }));
    vi.mocked(api.deleteConversation).mockResolvedValue();
  });

  it("lists conversations and marks the active one", async () => {
    setup();
    expect(await screen.findByText("NVDA vs AMD")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /NVDA vs AMD/ })).toHaveAttribute("aria-current", "true");
  });

  it("selects and starts new conversations", async () => {
    const p = setup();
    await userEvent.click(await screen.findByRole("button", { name: /Cohen review/ }));
    expect(p.onSelect).toHaveBeenCalledWith("desk_b");
    await userEvent.click(screen.getByRole("button", { name: "+ New conversation" }));
    expect(p.onNew).toHaveBeenCalled();
  });

  it("searches with the typed query", async () => {
    setup();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search conversations" }), "chips");
    await waitFor(() => expect(api.listConversations).toHaveBeenLastCalledWith("chips"));
  });

  it("renames inline", async () => {
    setup();
    await screen.findByText("NVDA vs AMD");
    await userEvent.click(screen.getAllByRole("button", { name: "Rename" })[0]);
    const box = screen.getByRole("textbox", { name: "Conversation title" });
    await userEvent.clear(box);
    await userEvent.type(box, "Chips{Enter}");
    expect(api.renameConversation).toHaveBeenCalledWith("desk_a", "Chips");
  });

  it("deletes after confirmation and reports it", async () => {
    const p = setup();
    await screen.findByText("NVDA vs AMD");
    await userEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    expect(screen.getByText("Delete this conversation? This cannot be undone.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(api.deleteConversation).toHaveBeenCalledWith("desk_a"));
    expect(p.onDeleted).toHaveBeenCalledWith("desk_a");
  });

  it("shows an error with Retry", async () => {
    vi.mocked(api.listConversations).mockRejectedValueOnce(new Error("down"));
    setup();
    expect(await screen.findByText("Couldn't load conversations")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("NVDA vs AMD")).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([]);
    setup();
    expect(await screen.findByText("No conversations yet")).toBeInTheDocument();
  });
});
