import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ReportFileCard } from "./ReportFileCard";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "report_file" }> = {
  type: "report_file",
  filename: "margaret-collins-portfolio-brief-2026-09-29.html",
  url: "/workspace/files/margaret-collins-portfolio-brief-2026-09-29.html",
};

describe("ReportFileCard", () => {
  it("shows the filename", () => {
    render(<ReportFileCard display={display} />);
    expect(screen.getByText(display.filename)).toBeInTheDocument();
  });

  it("links the download button at the report's url", () => {
    render(<ReportFileCard display={display} />);
    const link = screen.getByRole("link", { name: /download/i });
    expect(link).toHaveAttribute("href", display.url);
    expect(link).toHaveAttribute("download");
  });
});
