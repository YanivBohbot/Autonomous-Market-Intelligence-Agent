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

const multi: Extract<DisplayPayload, { type: "rag_sources" }> = {
  type: "rag_sources",
  sources: [
    { filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "Net sales increased 11%." },
    { filename: "Amazon-2024-10K.pdf", page: "50", excerpt: "Net income was $59,248 million." },
  ],
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

  it("narrows to the cited source when the reply's text precedes the tool message (this backend's actual order)", () => {
    fakeMessages = [
      { id: "u1", role: "user", content: "What was Amazon's net income in 2024?" },
      { id: "a1", role: "assistant", content: "", toolCallId: undefined },
      { id: "a2", role: "assistant", content: "Net income was $59,248 million [Source: Amazon-2024-10K.pdf, page 50]." },
      { id: "t1", role: "tool", toolCallId: "call_1" },
    ];
    render(<RagSourceCards display={multi} toolCallId="call_1" />);
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
    expect(screen.queryByText(/page 12/)).not.toBeInTheDocument();
  });

  it("also narrows when the tool message precedes the reply's text", () => {
    fakeMessages = [
      { id: "u1", role: "user", content: "What was Amazon's net income in 2024?" },
      { id: "t1", role: "tool", toolCallId: "call_1" },
      { id: "a2", role: "assistant", content: "Net income was $59,248 million [Source: Amazon-2024-10K.pdf, page 50]." },
    ];
    render(<RagSourceCards display={multi} toolCallId="call_1" />);
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
    expect(screen.queryByText(/page 12/)).not.toBeInTheDocument();
  });

  it("falls back to every source when nothing recognizable is cited", () => {
    fakeMessages = [
      { id: "u1", role: "user", content: "hi" },
      { id: "t1", role: "tool", toolCallId: "call_1" },
    ];
    render(<RagSourceCards display={multi} toolCallId="call_1" />);
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
  });

  it("falls back to every source when the tool message isn't found yet", () => {
    fakeMessages = [];
    render(<RagSourceCards display={multi} toolCallId="call_1" />);
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
  });

  it("only scans the current turn, ignoring an earlier turn's citation", () => {
    fakeMessages = [
      { id: "u0", role: "user", content: "earlier question" },
      { id: "a0", role: "assistant", content: "Earlier answer [Source: Amazon-2024-10K.pdf, page 12]." },
      { id: "u1", role: "user", content: "What was Amazon's net income in 2024?" },
      { id: "a1", role: "assistant", content: "Net income was $59,248 million [Source: Amazon-2024-10K.pdf, page 50]." },
      { id: "t1", role: "tool", toolCallId: "call_1" },
    ];
    render(<RagSourceCards display={multi} toolCallId="call_1" />);
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
    expect(screen.queryByText(/page 12/)).not.toBeInTheDocument();
  });
});
