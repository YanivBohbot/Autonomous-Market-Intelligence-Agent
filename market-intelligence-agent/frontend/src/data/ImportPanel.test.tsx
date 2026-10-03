import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import * as api from "../lib/api";
import { ImportPanel } from "./ImportPanel";

vi.mock("xlsx", () => ({
  read: vi.fn(() => ({ SheetNames: ["Sheet1"], Sheets: { Sheet1: {} } })),
  utils: { sheet_to_json: vi.fn(() => [{ client_email: "jane@x.com", ticker: "AAPL", shares: 10, avg_cost: 150 }]) },
}));

function selectFile(input: HTMLElement, file: File) {
  Object.defineProperty(input, "files", { value: [file] });
  fireEvent.change(input);
}

describe("ImportPanel", () => {
  it("uploads a .pdf directly and shows success", async () => {
    vi.spyOn(api, "importPdf").mockResolvedValue({ filename: "report.pdf", chunks_added: 5 });
    render(<ImportPanel />);
    const input = screen.getByLabelText(/choose a file/i);
    selectFile(input, new File(["%PDF"], "report.pdf", { type: "application/pdf" }));
    expect(await screen.findByText(/5 chunks/i)).toBeInTheDocument();
  });

  it("parses a .xlsx, shows a valid preview, and the Confirm button is enabled", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: true,
      rows: [{ client_id: 1, ticker: "AAPL", shares: 10, avg_cost: 150 }], errors: [],
    });
    render(<ImportPanel />);
    const input = screen.getByLabelText(/choose a file/i);
    selectFile(input, new File(["ignored"], "holdings.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /confirmer/i })).not.toBeDisabled());
  });

  it("disables Confirm and shows row errors for an invalid file", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: false, rows: [],
      errors: [{ row: 0, field: "client_email", message: "no client with this email" }],
    });
    render(<ImportPanel />);
    const input = screen.getByLabelText(/choose a file/i);
    selectFile(input, new File(["ignored"], "holdings.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    expect(await screen.findByText(/no client with this email/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /confirmer/i })).toBeDisabled();
  });

  it("clicking Confirm calls confirmImport with the previewed rows and type", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: true,
      rows: [{ client_id: 1, ticker: "AAPL", shares: 10, avg_cost: 150 }], errors: [],
    });
    const confirmSpy = vi.spyOn(api, "confirmImport").mockResolvedValue({ written: 1 });
    render(<ImportPanel />);
    const input = screen.getByLabelText(/choose a file/i);
    selectFile(input, new File(["ignored"], "holdings.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    const confirmButton = await screen.findByRole("button", { name: /confirmer/i });
    await waitFor(() => expect(confirmButton).not.toBeDisabled());
    fireEvent.click(confirmButton);
    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith("holdings", [{ client_id: 1, ticker: "AAPL", shares: 10, avg_cost: 150 }]));
  });
});
