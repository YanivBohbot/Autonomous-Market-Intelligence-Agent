import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DocumentsList } from "./DocumentsList";

describe("DocumentsList", () => {
  it("renders each ingested filename", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ["report-a.pdf", "report-b.pdf"] }));
    render(<DocumentsList />);
    expect(await screen.findByText("report-a.pdf")).toBeInTheDocument();
    expect(screen.getByText("report-b.pdf")).toBeInTheDocument();
  });

  it("renders a message when no documents are ingested yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DocumentsList />);
    expect(await screen.findByText(/no documents/i)).toBeInTheDocument();
  });
});
