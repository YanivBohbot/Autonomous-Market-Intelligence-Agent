import { describe, it, expect, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { DisplayPayload } from "./types";

type Subscriber = { onEvent?: (p: { event: unknown }) => void };
const subscribers: Subscriber[] = [];
const fakeAgent = {
  subscribe: (s: Subscriber) => {
    subscribers.push(s);
    return { unsubscribe: () => undefined };
  },
};
vi.mock("@copilotkit/react-core/v2", () => ({ useAgent: () => ({ agent: fakeAgent }) }));

const { RagSourceCards } = await import("./RagSourceCards");

function emit(event: unknown) {
  act(() => subscribers[subscribers.length - 1]?.onEvent?.({ event }));
}

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

  it("narrows to only the source the reply cites, as its text streams in", () => {
    const multi: Extract<DisplayPayload, { type: "rag_sources" }> = {
      type: "rag_sources",
      sources: [
        { filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "Net sales increased 11%." },
        { filename: "Amazon-2024-10K.pdf", page: "50", excerpt: "Net income was $59,248 million." },
      ],
    };
    render(<RagSourceCards display={multi} />);
    emit({ type: "RUN_STARTED" });
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
    emit({
      type: "TEXT_MESSAGE_CONTENT",
      delta: "Net income was $59,248 million [Source: Amazon-2024-10K.pdf, page 50].",
    });
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
    expect(screen.queryByText(/page 12/)).not.toBeInTheDocument();
  });

  it("falls back to every source before any citation has streamed", () => {
    const multi: Extract<DisplayPayload, { type: "rag_sources" }> = {
      type: "rag_sources",
      sources: [
        { filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "a" },
        { filename: "Amazon-2024-10K.pdf", page: "50", excerpt: "b" },
      ],
    };
    render(<RagSourceCards display={multi} />);
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
  });

  it("resets to every source when a new run starts", () => {
    const multi: Extract<DisplayPayload, { type: "rag_sources" }> = {
      type: "rag_sources",
      sources: [
        { filename: "Amazon-2024-10K.pdf", page: "12", excerpt: "a" },
        { filename: "Amazon-2024-10K.pdf", page: "50", excerpt: "b" },
      ],
    };
    render(<RagSourceCards display={multi} />);
    emit({ type: "RUN_STARTED" });
    emit({ type: "TEXT_MESSAGE_CONTENT", delta: "[Source: Amazon-2024-10K.pdf, page 50]" });
    expect(screen.queryByText(/page 12/)).not.toBeInTheDocument();
    emit({ type: "RUN_STARTED" });
    expect(screen.getByText(/page 12/)).toBeInTheDocument();
    expect(screen.getByText(/page 50/)).toBeInTheDocument();
  });
});
