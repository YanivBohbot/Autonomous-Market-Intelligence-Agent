import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DataPage } from "./DataPage";

describe("DataPage", () => {
  it("renders the shared page header and accessible tabs", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));

    render(<DataPage />);

    expect(screen.getByRole("heading", { name: "Data" })).toBeInTheDocument();
    expect(screen.getByRole("tablist", { name: "Data workspace" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Documents" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Import" })).toHaveAttribute("aria-selected", "false");
    expect(screen.queryByRole("tab", { name: "Clients" })).not.toBeInTheDocument();
    expect(await screen.findByText("No documents ingested yet")).toBeInTheDocument();
  });

  it("switches the selected tab and visible tabpanel", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DataPage />);

    await user.click(screen.getByRole("tab", { name: "Import" }));

    expect(screen.getByRole("tab", { name: "Import" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel", { name: "Import" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose a file to import" })).toBeInTheDocument();
  });
});
