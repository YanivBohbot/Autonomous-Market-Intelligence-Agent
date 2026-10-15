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
    localStorage.clear();
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

  it("shows the just-started conversation at the top before its first question", async () => {
    setup("desk_new");
    const row = await screen.findByRole("button", { name: /^New conversation/ });
    expect(row).toHaveAttribute("aria-current", "true");
    expect(screen.getAllByRole("listitem")[0]).toHaveTextContent("New conversation");
    expect(screen.getAllByRole("button", { name: "Rename" })).toHaveLength(rows.length);
  });

  it("drops the placeholder once the conversation is listed", async () => {
    setup("desk_a");
    await screen.findByText("NVDA vs AMD");
    expect(screen.getAllByRole("listitem")).toHaveLength(rows.length);
  });

  it("hides the placeholder while searching", async () => {
    setup("desk_new");
    await screen.findByRole("button", { name: /^New conversation/ });
    await userEvent.type(screen.getByRole("searchbox", { name: "Search conversations" }), "chips");
    await waitFor(() => expect(screen.queryByRole("button", { name: /^New conversation/ })).not.toBeInTheDocument());
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

  it("shows only the new conversation when the history is empty", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([]);
    setup();
    expect(await screen.findByRole("button", { name: /^New conversation/ })).toBeInTheDocument();
    expect(screen.queryByText("No conversations yet")).not.toBeInTheDocument();
  });

  it("says so when a search finds nothing", async () => {
    vi.mocked(api.listConversations).mockResolvedValue([]);
    setup();
    await userEvent.type(screen.getByRole("searchbox", { name: "Search conversations" }), "zzz");
    expect(await screen.findByText("No matching conversations")).toBeInTheDocument();
  });

  it("collapses to a thin rail and expands again, remembering the choice", async () => {
    setup();
    await screen.findByText("NVDA vs AMD");
    await userEvent.click(screen.getByRole("button", { name: "Hide conversations" }));
    expect(screen.queryByText("NVDA vs AMD")).not.toBeInTheDocument();
    expect(screen.queryByRole("searchbox", { name: "Search conversations" })).not.toBeInTheDocument();
    expect(localStorage.getItem("research.conversations.collapsed")).toBe("1");
    await userEvent.click(screen.getByRole("button", { name: "Show conversations" }));
    expect(await screen.findByText("NVDA vs AMD")).toBeInTheDocument();
    expect(localStorage.getItem("research.conversations.collapsed")).toBe("0");
  });

  it("starts collapsed when that was the last choice, and can still start a new conversation", async () => {
    localStorage.setItem("research.conversations.collapsed", "1");
    const p = setup();
    expect(screen.getByRole("button", { name: "Show conversations" })).toBeInTheDocument();
    expect(screen.queryByText("NVDA vs AMD")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "New conversation" }));
    expect(p.onNew).toHaveBeenCalled();
  });

  it("shows an error and keeps the row when delete fails", async () => {
    vi.mocked(api.deleteConversation).mockRejectedValueOnce(new Error("409"));
    const p = setup();
    await screen.findByText("NVDA vs AMD");
    await userEvent.click(screen.getAllByRole("button", { name: "Delete" })[0]);
    await userEvent.click(screen.getByRole("button", { name: "Confirm delete" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't delete this conversation");
    expect(screen.getByText("NVDA vs AMD")).toBeInTheDocument();
    expect(p.onDeleted).not.toHaveBeenCalled();
  });

  it("shows an error when rename fails", async () => {
    vi.mocked(api.renameConversation).mockRejectedValueOnce(new Error("500"));
    setup();
    await screen.findByText("NVDA vs AMD");
    await userEvent.click(screen.getAllByRole("button", { name: "Rename" })[0]);
    const box = screen.getByRole("textbox", { name: "Conversation title" });
    await userEvent.clear(box);
    await userEvent.type(box, "Chips{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't rename this conversation");
    expect(screen.getByText("NVDA vs AMD")).toBeInTheDocument();
  });

  it("ignores a slow search answer that arrives after a newer request", async () => {
    let resolveSearch: (found: api.Conversation[]) => void = () => undefined;
    vi.mocked(api.listConversations).mockImplementation((q?: string) =>
      q ? new Promise((r) => { resolveSearch = r; }) : Promise.resolve(rows),
    );
    setup();
    await screen.findByText("NVDA vs AMD");
    const box = screen.getByRole("searchbox", { name: "Search conversations" });
    await userEvent.type(box, "chips");
    await waitFor(() => expect(api.listConversations).toHaveBeenLastCalledWith("chips"));
    await userEvent.clear(box);
    await waitFor(() => expect(api.listConversations).toHaveBeenLastCalledWith(""));
    resolveSearch([]);
    await new Promise((r) => setTimeout(r, 50));
    expect(screen.getByText("NVDA vs AMD")).toBeInTheDocument();
    expect(screen.getByText("Cohen review")).toBeInTheDocument();
  });
});
