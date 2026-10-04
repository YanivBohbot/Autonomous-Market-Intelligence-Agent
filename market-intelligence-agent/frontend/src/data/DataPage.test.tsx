import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { DataPage } from "./DataPage";

describe("DataPage", () => {
  it("only shows the Documents and Import tabs", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DataPage />);
    expect(screen.getByRole("button", { name: "Documents" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Clients" })).not.toBeInTheDocument();
  });

  it("defaults to the Documents tab", () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DataPage />);
    expect(screen.getByRole("button", { name: "Documents" })).toHaveClass("text-terminal-accent");
  });
});
