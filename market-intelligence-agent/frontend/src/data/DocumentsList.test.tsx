import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DocumentsList } from "./DocumentsList";

describe("DocumentsList", () => {
  it("shows a local skeleton while documents load", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));

    render(<DocumentsList />);

    expect(screen.getByRole("status", { name: "Loading documents" })).toBeInTheDocument();
  });

  it("renders document cards with PDF, Excel, and generic file icons", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ["brief.pdf", "holdings.xlsx", "notes.txt"] }));

    render(<DocumentsList />);

    expect(await screen.findByText("brief.pdf")).toBeInTheDocument();
    expect(screen.getByText("holdings.xlsx")).toBeInTheDocument();
    expect(screen.getByText("notes.txt")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "PDF document" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Excel document" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Generic document" })).toBeInTheDocument();
  });

  it("renders an intentional empty state", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DocumentsList />);

    expect(await screen.findByText("No documents ingested yet")).toBeInTheDocument();
  });

  it("shows a retryable error and recovers", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 500, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: true, json: async () => ["brief.pdf"] });
    vi.stubGlobal("fetch", fetchMock);
    render(<DocumentsList />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Documents unavailable");
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("brief.pdf")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});
