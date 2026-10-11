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
  client_name: "Margaret Collins",
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

  it("loads every generated report without selecting one", async () => {
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
    render(<EmailAttachmentSelector value="" onChange={onChange} />);

    expect(screen.getByRole("status")).toHaveTextContent("Loading generated reports");
    await finishDebounce();

    expect(screen.getByRole("option", { name: /Margaret Collins.*margaret-collins/ })).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Attachment (optional)" })).toHaveValue("");
    expect(onChange).not.toHaveBeenCalled();
    expect(getGeneratedReportsMock).toHaveBeenCalledWith();
  });

  it("shows an empty state without changing the selection", async () => {
    getGeneratedReportsMock.mockResolvedValue([]);
    render(<EmailAttachmentSelector value="" onChange={onChange} />);
    await finishDebounce();

    expect(screen.getByText("No generated reports available")).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps no-attachment usable when loading fails", async () => {
    getGeneratedReportsMock.mockRejectedValue(new Error("503"));
    render(<EmailAttachmentSelector value="" onChange={onChange} />);
    await finishDebounce();

    expect(screen.getByRole("alert")).toHaveTextContent("Generated reports unavailable");
    expect(screen.getByRole("option", { name: "No attachment" })).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("returns a manually selected filename", async () => {
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
    render(<EmailAttachmentSelector value="" onChange={onChange} />);
    await finishDebounce();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: REPORT.filename } });
    expect(onChange).toHaveBeenCalledWith(REPORT.filename);
  });

  it("shows selected report details and removes the attachment", async () => {
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
    render(<EmailAttachmentSelector value={REPORT.filename} onChange={onChange} />);
    await finishDebounce();

    expect(screen.getByText("Selected report")).toBeInTheDocument();
    expect(screen.getByText("Margaret Collins")).toBeInTheDocument();
    expect(screen.getByText(REPORT.filename)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove attachment" }));
    expect(onChange).toHaveBeenCalledWith("");
  });

  it("does not reload or clear a valid selected report on rerender", async () => {
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
    const { rerender } = render(
      <EmailAttachmentSelector value={REPORT.filename} onChange={onChange} />,
    );
    await finishDebounce();
    expect(onChange).not.toHaveBeenCalled();

    rerender(
      <EmailAttachmentSelector value={REPORT.filename} onChange={onChange} />,
    );

    expect(onChange).not.toHaveBeenCalled();
    expect(getGeneratedReportsMock).toHaveBeenCalledTimes(1);
  });

  it("disables selection when edits are forbidden", async () => {
    getGeneratedReportsMock.mockResolvedValue([REPORT]);
    render(
      <EmailAttachmentSelector value="" disabled onChange={onChange} />,
    );
    await finishDebounce();

    expect(screen.getByRole("combobox")).toBeDisabled();
  });
});
