import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DisplayPayload } from "./types";

type FakeMessage = { id: string; role: string; content?: string; toolCallId?: string };
let fakeMessages: FakeMessage[] = [];
vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({ agent: { get messages() { return fakeMessages; } } }),
}));

const { RagSourceCards } = await import("./RagSourceCards");

const display: Extract<DisplayPayload, { type: "rag_sources" }> = {
  type: "rag_sources",
  sources: [{ filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "Net sales increased 11%." }],
};

describe("RagSourceCards", () => {
  it("shows the filename and page, collapsed by default", () => {
    fakeMessages = [];
    render(<RagSourceCards display={display} />);
    expect(screen.getByText(/Amazon-2024-10K.pdf/)).toBeInTheDocument();
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.queryByText("Net sales increased 11%.")).not.toBeInTheDocument();
  });

  it("expands the excerpt on click", async () => {
    fakeMessages = [];
    const user = userEvent.setup();
    render(<RagSourceCards display={display} />);
    await user.click(screen.getByText(/Amazon-2024-10K.pdf/));
    expect(screen.getByText("Net sales increased 11%.")).toBeInTheDocument();
  });

  it("narrows to only the source the reply actually cites", () => {
    const multi: Extract<DisplayPayload, { type: "rag_sources" }> = {
      type: "rag_sources",
      sources: [
        { filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "Net sales increased 11%." },
        { filename: "Amazon-2024-10K.pdf", page: "50", excerpt: "Net income was $59,248 million." },
      ],
    };
    fakeMessages = [
      { id: "t1", role: "tool", toolCallId: "call_1" },
      { id: "a1", role: "assistant", content: "Net income was $59,248 million [Source: Amazon-2024-10K.pdf, page 50]." },
    ];
    render(<RagSourceCards display={multi} toolCallId="call_1" />);
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
    expect(screen.queryByText(/page 12/)).not.toBeInTheDocument();
  });

  it("falls back to every source when the reply hasn't cited one yet", () => {
    const multi: Extract<DisplayPayload, { type: "rag_sources" }> = {
      type: "rag_sources",
      sources: [
        { filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "a" },
        { filename: "Amazon-2024-10K.pdf", page: "50", excerpt: "b" },
      ],
    };
    fakeMessages = [{ id: "t1", role: "tool", toolCallId: "call_1" }];
    render(<RagSourceCards display={multi} toolCallId="call_1" />);
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
  });
});
