import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RagSourceCards } from "./RagSourceCards";
import type { DisplayPayload } from "./types";

const display: Extract<DisplayPayload, { type: "rag_sources" }> = {
  type: "rag_sources",
  sources: [{ filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "Net sales increased 11%." }],
};

describe("RagSourceCards", () => {
  it("shows the filename and page, collapsed by default", () => {
    render(<RagSourceCards display={display} />);
    expect(screen.getByText(/Amazon-2024-10K.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.queryByText("Net sales increased 11%.")).not.toBeInTheDocument();
  });

  it("expands the excerpt on click", async () => {
    const user = userEvent.setup();
    render(<RagSourceCards display={display} />);
    await user.click(screen.getByText(/Amazon-2024-10K.pdf/));
    expect(screen.getByText("Net sales increased 11%.")).toBeInTheDocument();
  });
});
