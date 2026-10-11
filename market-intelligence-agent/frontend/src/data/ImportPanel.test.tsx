import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as XLSX from "xlsx";
import * as api from "../lib/api";
import { ImportPanel } from "./ImportPanel";

const HOLDING_ROW = { client_email: "jane@x.com", ticker: "AAPL", shares: 10, avg_cost: 150 };

vi.mock("xlsx", () => ({
  read: vi.fn(() => ({ SheetNames: ["Sheet1"], Sheets: { Sheet1: {} } })),
  utils: { sheet_to_json: vi.fn(() => [HOLDING_ROW]) },
}));

function fileInput() {
  return screen.getByLabelText("Choose file") as HTMLInputElement;
}

function selectFile(file: File) {
  const input = fileInput();
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  fireEvent.change(input);
}

function uploadSelected() {
  fireEvent.click(screen.getByRole("button", { name: "Upload selected file" }));
}

function selectAndUpload(file: File) {
  selectFile(file);
  uploadSelected();
}

function dropFile(file: File) {
  fireEvent.drop(screen.getByRole("button", { name: "Choose a file to import" }), {
    dataTransfer: { files: [file] },
  });
}

describe("ImportPanel", () => {
  beforeEach(() => {
    vi.mocked(XLSX.utils.sheet_to_json).mockReset().mockReturnValue([HOLDING_ROW]);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("opens the hidden file picker with Enter and Space", async () => {
    const user = userEvent.setup();
    render(<ImportPanel />);
    const clickSpy = vi.spyOn(fileInput(), "click");
    const dropZone = screen.getByRole("button", { name: "Choose a file to import" });

    dropZone.focus();
    await user.keyboard("{Enter}");
    await user.keyboard(" ");

    expect(clickSpy).toHaveBeenCalledTimes(2);
  });

  it("shows a distinct drag-enter state and clears it on drag-leave", () => {
    render(<ImportPanel />);
    const dropZone = screen.getByRole("button", { name: "Choose a file to import" });

    fireEvent.dragEnter(dropZone);
    expect(dropZone).toHaveAttribute("data-dragging", "true");
    expect(screen.getByText("Drop file here")).toBeInTheDocument();
    fireEvent.dragLeave(dropZone);
    expect(dropZone).toHaveAttribute("data-dragging", "false");
  });

  it("accepts a dropped PDF, uploads it directly, and shows success", async () => {
    vi.spyOn(api, "importPdf").mockResolvedValue({ filename: "report.pdf", chunks_added: 5 });
    render(<ImportPanel />);

    dropFile(new File(["%PDF"], "report.pdf", { type: "application/pdf" }));
    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    uploadSelected();

    expect(await screen.findByText(/5 chunks added/i)).toBeInTheDocument();
  });

  it("accepts a dropped Excel file and shows a valid preview", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: true,
      rows: [{ client_id: 1, ticker: "AAPL", shares: 10, avg_cost: 150 }], errors: [],
    });
    render(<ImportPanel />);

    dropFile(new File(["ignored"], "holdings.xlsx", { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" }));
    uploadSelected();

    expect(await screen.findByText("1 row(s) ready to import.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm import" })).not.toBeDisabled();
  });

  it("rejects unsupported extensions before any import API call", () => {
    const pdfSpy = vi.spyOn(api, "importPdf");
    const previewSpy = vi.spyOn(api, "previewImport");
    render(<ImportPanel />);

    dropFile(new File(["text"], "notes.txt", { type: "text/plain" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Unsupported file type");
    expect(screen.getByRole("button", { name: "Upload selected file" })).toBeDisabled();
    expect(pdfSpy).not.toHaveBeenCalled();
    expect(previewSpy).not.toHaveBeenCalled();
  });

  it("disables confirmation and shows validation errors for an invalid preview", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: false, rows: [],
      errors: [{ row: 0, field: "client_email", message: "no client with this email" }],
    });
    render(<ImportPanel />);

    selectAndUpload(new File(["ignored"], "holdings.xlsx"));

    expect(await screen.findByText(/no client with this email/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm import" })).toBeDisabled();
  });

  it("confirms a holdings import with raw parsed rows and shows success", async () => {
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "holdings", valid: true,
      rows: [{ client_id: 1, ticker: "AAPL", shares: 10, avg_cost: 150 }], errors: [],
    });
    const confirmSpy = vi.spyOn(api, "confirmImport").mockResolvedValue({ written: 1 });
    render(<ImportPanel />);

    selectAndUpload(new File(["ignored"], "holdings.xlsx"));
    await screen.findByText("1 row(s) ready to import.");
    fireEvent.click(screen.getByRole("button", { name: "Confirm import" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith("holdings", [HOLDING_ROW]));
    expect(await screen.findByText("Imported 1 row(s).")).toBeInTheDocument();
  });

  it("confirms a clients import with raw parsed rows", async () => {
    const rawClient = { name: "Jane Doe", email: "jane@x.com", segment: "VIP", risk_profile: "balanced", advisor: "Sam", city: "Paris" };
    vi.mocked(XLSX.utils.sheet_to_json).mockReturnValueOnce([rawClient]);
    vi.spyOn(api, "previewImport").mockResolvedValue({
      type: "clients", valid: true,
      rows: [{ ...rawClient, joined_on: "2026-10-04" }], errors: [],
    });
    const confirmSpy = vi.spyOn(api, "confirmImport").mockResolvedValue({ written: 1 });
    render(<ImportPanel />);

    selectAndUpload(new File(["ignored"], "clients.xls"));
    await screen.findByText("1 row(s) ready to import.");
    fireEvent.click(screen.getByRole("button", { name: "Confirm import" }));

    await waitFor(() => expect(confirmSpy).toHaveBeenCalledWith("clients", [rawClient]));
  });

  it("resets selection so the same file can be processed twice", async () => {
    const previewSpy = vi.spyOn(api, "previewImport").mockResolvedValue({ type: "holdings", valid: true, rows: [], errors: [] });
    render(<ImportPanel />);
    const file = new File(["ignored"], "holdings.xlsx");

    selectAndUpload(file);
    await waitFor(() => expect(previewSpy).toHaveBeenCalledTimes(1));
    expect(fileInput().value).toBe("");
    selectAndUpload(file);

    await waitFor(() => expect(previewSpy).toHaveBeenCalledTimes(2));
  });

  it("shows an unrecognized-format error returned by preview validation", async () => {
    vi.spyOn(api, "previewImport").mockRejectedValue(new Error("unrecognized file format"));
    render(<ImportPanel />);

    selectAndUpload(new File(["ignored"], "mystery.xlsx"));

    expect(await screen.findByRole("alert")).toHaveTextContent("unrecognized file format");
  });

  it("sends an empty row array to preview validation", async () => {
    vi.mocked(XLSX.utils.sheet_to_json).mockReturnValueOnce([]);
    const previewSpy = vi.spyOn(api, "previewImport").mockResolvedValue({ type: "holdings", valid: true, rows: [], errors: [] });
    render(<ImportPanel />);

    selectAndUpload(new File(["ignored"], "empty.xlsx"));

    await waitFor(() => expect(previewSpy).toHaveBeenCalledWith([]));
  });
});
