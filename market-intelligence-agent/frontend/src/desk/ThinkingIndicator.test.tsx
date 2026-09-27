import { describe, it, expect, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";

type Subscriber = {
  onEvent?: (p: { event: unknown }) => void;
  onRunFailed?: (p: { error: Error }) => void;
};
const subscribers: Subscriber[] = [];
const fakeAgent = {
  subscribe: (s: Subscriber) => {
    subscribers.push(s);
    return { unsubscribe: () => undefined };
  },
};
vi.mock("@copilotkit/react-core/v2", () => ({ useAgent: () => ({ agent: fakeAgent }) }));

import { ThinkingIndicator } from "./ThinkingIndicator";

function emit(event: unknown) {
  act(() => subscribers[subscribers.length - 1]?.onEvent?.({ event }));
}

describe("ThinkingIndicator", () => {
  it("renders nothing before a run starts", () => {
    render(<ThinkingIndicator />);
    expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
  });

  it("shows a generic Thinking label right after a run starts", () => {
    render(<ThinkingIndicator />);
    emit({ type: "RUN_STARTED" });
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
  });

  it("updates the label when a specialist starts working", () => {
    render(<ThinkingIndicator />);
    emit({ type: "RUN_STARTED" });
    emit({ type: "STEP_STARTED", stepName: "portfolio_agent" });
    expect(screen.getByText("Analyzing the portfolio...")).toBeInTheDocument();
  });

  it("updates the label when a tool call starts", () => {
    render(<ThinkingIndicator />);
    emit({ type: "RUN_STARTED" });
    emit({ type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "yfinance_get_price_history" });
    expect(screen.getByText("Running yfinance_get_price_history...")).toBeInTheDocument();
  });

  it("hides once the assistant's answer starts streaming", () => {
    render(<ThinkingIndicator />);
    emit({ type: "RUN_STARTED" });
    emit({ type: "TEXT_MESSAGE_CONTENT", delta: "The" });
    expect(screen.queryByText(/Thinking|Running|Analyzing/)).not.toBeInTheDocument();
  });

  it("hides when the run finishes", () => {
    render(<ThinkingIndicator />);
    emit({ type: "RUN_STARTED" });
    emit({ type: "RUN_FINISHED" });
    expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
  });

  it("hides on a run error", () => {
    render(<ThinkingIndicator />);
    emit({ type: "RUN_STARTED" });
    emit({ type: "RUN_ERROR", message: "boom" });
    expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
  });

  it("hides on a transport failure (onRunFailed, no RUN_ERROR event)", () => {
    render(<ThinkingIndicator />);
    emit({ type: "RUN_STARTED" });
    act(() => subscribers[subscribers.length - 1]?.onRunFailed?.({ error: new Error("HTTP 404") }));
    expect(screen.queryByText(/Thinking/)).not.toBeInTheDocument();
  });

  it("resets to the generic label on a new run after a previous one finished", () => {
    render(<ThinkingIndicator />);
    emit({ type: "RUN_STARTED" });
    emit({ type: "STEP_STARTED", stepName: "rag_agent" });
    emit({ type: "RUN_FINISHED" });
    emit({ type: "RUN_STARTED" });
    expect(screen.getByText("Thinking...")).toBeInTheDocument();
  });
});
