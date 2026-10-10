import { act, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { VoiceActivityEvent } from "../voice/types";

type Subscriber = {
  onEvent?: (payload: { event: unknown }) => void;
  onRunFailed?: (payload: { error: Error }) => void;
};

const subscribers: Subscriber[] = [];
const unsubscribe = vi.fn();
const subscribe = vi.fn((subscriber: Subscriber) => {
  subscribers.push(subscriber);
  return { unsubscribe };
});
const fakeAgent = { subscribe };

vi.mock("@copilotkit/react-core/v2", () => ({ useAgent: () => ({ agent: fakeAgent }) }));

import { DeskActivityRail } from "./DeskActivityRail";

function latestSubscriber(): Subscriber {
  const subscriber = subscribers[subscribers.length - 1];
  if (!subscriber) throw new Error("DeskActivityRail did not subscribe");
  return subscriber;
}

function emit(event: unknown) {
  act(() => latestSubscriber().onEvent?.({ event }));
}

describe("DeskActivityRail", () => {
  let now = 1_000;

  beforeEach(() => {
    subscribers.length = 0;
    subscribe.mockClear();
    unsubscribe.mockClear();
    now = 1_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("subscribes once, starts in a helpful ready state, and unsubscribes", () => {
    const view = render(<DeskActivityRail />);
    expect(subscribe).toHaveBeenCalledOnce();
    expect(screen.getByText("System ready")).toBeInTheDocument();
    expect(screen.getByText(/activity will appear/i)).toBeInTheDocument();

    view.unmount();
    expect(unsubscribe).toHaveBeenCalledOnce();
  });

  it("renders supervisor, a humanized timed tool, completion, and token count", () => {
    render(<DeskActivityRail />);
    emit({ type: "STEP_STARTED", stepName: "supervisor_agent" });
    now = 1_100;
    emit({ type: "STEP_STARTED", stepName: "finance_agent" });
    now = 1_200;
    emit({ type: "TOOL_CALL_START", toolCallId: "call-1", toolCallName: "yfinance_ticker_info" });
    now = 1_450;
    emit({ type: "TOOL_CALL_RESULT", toolCallId: "call-1", content: "{}" });
    now = 1_500;
    emit({ type: "RUN_FINISHED", usage: { totalTokens: 1234 } });

    expect(screen.getByText("Supervisor")).toBeInTheDocument();
    expect(screen.getByText("Finance")).toBeInTheDocument();
    expect(screen.getByText("Ticker info")).toBeInTheDocument();
    expect(screen.getByText("250 ms")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("1,234 tokens")).toBeInTheDocument();
  });

  it("labels a running or approval-waiting newest group as Current run", () => {
    render(<DeskActivityRail />);
    emit({ type: "STEP_STARTED", stepName: "rag_agent" });
    now = 1_100;
    emit({ type: "RUN_FINISHED" });
    now = 1_200;
    emit({ type: "STEP_STARTED", stepName: "email_agent" });
    now = 1_300;
    emit({ type: "TOOL_CALL_START", toolCallId: "mail-1", toolCallName: "send_email" });
    now = 1_400;
    emit({ type: "RUN_FINISHED", outcome: { type: "interrupt" } });

    const runs = screen.getAllByTestId("activity-run");
    expect(within(runs[0]).getByText("Current run")).toBeInTheDocument();
    expect(within(runs[0]).getByText("Awaiting approval")).toBeInTheDocument();
    expect(within(runs[0]).getByText("Send email")).toBeInTheDocument();
    expect(within(runs[1]).getByText("Completed")).toBeInTheDocument();
  });

  it("shows a transport failure as the newest failed run", () => {
    render(<DeskActivityRail />);
    act(() => latestSubscriber().onRunFailed?.({ error: new Error("HTTP 404: Not Found") }));

    const run = screen.getByTestId("activity-run");
    expect(within(run).getByText("Run failed")).toBeInTheDocument();
    expect(within(run).getByText("HTTP 404: Not Found")).toBeInTheDocument();
  });

  it("adds voice events once, in sequence order, through the same timeline", () => {
    const voiceEvents: VoiceActivityEvent[] = [
      { sequence: 1, run_id: "voice-1", kind: "specialist_started", name: "finance_agent", tool_call_id: null, duration_ms: null, message: null },
      { sequence: 2, run_id: "voice-1", kind: "tool_started", name: "portfolio_metrics", tool_call_id: "voice-call-1", duration_ms: null, message: null },
      { sequence: 3, run_id: "voice-1", kind: "tool_finished", name: "portfolio_metrics", tool_call_id: "voice-call-1", duration_ms: 1250, message: null },
      { sequence: 4, run_id: "voice-1", kind: "approval_required", name: null, tool_call_id: null, duration_ms: null, message: null },
    ];
    const view = render(<DeskActivityRail voiceEvents={voiceEvents} />);

    expect(screen.getAllByText("Finance")).toHaveLength(1);
    expect(screen.getAllByText("Portfolio metrics")).toHaveLength(1);
    expect(screen.getByText("1.3 s")).toBeInTheDocument();
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();

    view.rerender(<DeskActivityRail voiceEvents={[...voiceEvents]} />);
    expect(screen.getAllByText("Finance")).toHaveLength(1);
    expect(screen.getAllByText("Portfolio metrics")).toHaveLength(1);

    view.rerender(
      <DeskActivityRail
        voiceEvents={[
          ...voiceEvents,
          { sequence: 5, run_id: "voice-2", kind: "specialist_started", name: "rag_agent", tool_call_id: null, duration_ms: null, message: null },
          { sequence: 6, run_id: "voice-2", kind: "run_finished", name: null, tool_call_id: null, duration_ms: null, message: null },
          { sequence: 7, run_id: "voice-3", kind: "run_error", name: null, tool_call_id: null, duration_ms: null, message: "Voice processing failed" },
        ]}
      />,
    );

    expect(screen.getAllByText("Finance")).toHaveLength(1);
    expect(screen.getByText("RAG")).toBeInTheDocument();
    expect(screen.getByText("Completed")).toBeInTheDocument();
    expect(screen.getByText("Voice processing failed")).toBeInTheDocument();
    expect(screen.getAllByTestId("activity-run")).toHaveLength(3);
  });
});
