import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen } from "@testing-library/react";

const getGeneratedReportsMock = vi.fn();

vi.mock("../lib/api", () => ({
  getGeneratedReports: (...args: unknown[]) => getGeneratedReportsMock(...args),
}));

import { EmailAttachmentSelector } from "./EmailAttachmentSelector";

const REPORT = {
  filename: "margaret-collins-portfolio-brief-2026-10-06.xlsx",
  generated_at: "2026-10-06T09:30:00+00:00",
  size_bytes: 24832,
};

async function finishDebounce() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(250);
  });
}

describe("EmailAttachmentSelector", () => {
  const onChange = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    getGeneratedReportsMock.mockReset();
    onChange.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("loads recipient reports without selecting one", async () => {
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
    render(<EmailAttachmentSelector recipient="margaret@example.com" value="" onChange={onChange} />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading generated reports");
    await finishDebounce();

    expect(screen.getByRole("option", { name: /margaret-collins/ })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Attachment (optional)" })).toHaveValue("");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("shows an empty state without changing the selection", async () => {
    getGeneratedReportsMock.mockResolvedValue([]);
    render(<EmailAttachmentSelector recipient="margaret@example.com" value="" onChange={onChange} />);
    await finishDebounce();

    expect(screen.getByText("No generated reports available")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps no-attachment usable when loading fails", async () => {
    getGeneratedReportsMock.mockRejectedValue(new Error("503"));
    render(<EmailAttachmentSelector recipient="margaret@example.com" value="" onChange={onChange} />);
    await finishDebounce();

    expect(screen.getByRole("alert")).toHaveTextContent("Generated reports unavailable");
    expect(screen.getByRole("option", { name: "No attachment" })).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("returns a manually selected filename", async () => {
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
    render(<EmailAttachmentSelector recipient="margaret@example.com" value="" onChange={onChange} />);
    await finishDebounce();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: REPORT.filename } });
    expect(onChange).toHaveBeenCalledWith(REPORT.filename);
  });

  it("clears a stale selection after the recipient changes", async () => {
    getGeneratedReportsMock
      .mockResolvedValueOnce([REPORT])
      .mockResolvedValueOnce([]);
    const { rerender } = render(
      <EmailAttachmentSelector recipient="margaret@example.com" value={REPORT.filename} onChange={onChange} />,
    );
    await finishDebounce();
    expect(onChange).not.toHaveBeenCalled();

    rerender(
      <EmailAttachmentSelector recipient="jane@example.com" value={REPORT.filename} onChange={onChange} />,
    );
    await finishDebounce();

    expect(onChange).toHaveBeenCalledWith("");
  });

  it("clears a stale selection on recipient change even when refresh fails", async () => {
    getGeneratedReportsMock
      .mockResolvedValueOnce([REPORT])
      .mockRejectedValueOnce(new Error("503"));
    const { rerender } = render(
      <EmailAttachmentSelector recipient="margaret@example.com" value={REPORT.filename} onChange={onChange} />,
    );
    await finishDebounce();
    expect(onChange).not.toHaveBeenCalled();

    rerender(
      <EmailAttachmentSelector recipient="jane@example.com" value={REPORT.filename} onChange={onChange} />,
    );
    await finishDebounce();

    expect(onChange).toHaveBeenCalledWith("");
    expect(screen.getByRole("alert")).toHaveTextContent("Generated reports unavailable");
  });

  it("disables selection when edits are forbidden", async () => {
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
    render(
      <EmailAttachmentSelector recipient="margaret@example.com" value="" disabled onChange={onChange} />,
    );
    await finishDebounce();

    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});
