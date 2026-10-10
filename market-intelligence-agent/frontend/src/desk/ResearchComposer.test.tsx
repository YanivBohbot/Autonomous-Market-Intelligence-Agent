import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatInput: ({
    startTranscribeButton: StartTranscribeButton,
    onStartTranscribe,
  }: {
    startTranscribeButton?: React.ComponentType<React.ButtonHTMLAttributes<HTMLButtonElement>>;
    onStartTranscribe?: () => void;
  }) => (
    <div>
      <textarea aria-label="Research message" />
      {StartTranscribeButton && (
        <StartTranscribeButton onClick={onStartTranscribe} />
      )}
    </div>
  ),
}));

import {
  ResearchVoiceContext,
  type ResearchVoiceContextValue,
} from "../voice/ResearchVoiceContext";
import { ResearchComposer } from "./ResearchComposer";

function voiceValue(
  overrides: Partial<ResearchVoiceContextValue> = {},
): ResearchVoiceContextValue {
  return {
    enabled: true,
    phase: "disconnected",
    active: false,
    events: [],
    pending: null,
    error: null,
    typedApprovalPending: false,
    start: vi.fn(),
    end: vi.fn(),
    submitDecision: vi.fn(),
    setTypedApprovalPending: vi.fn(),
    ...overrides,
  };
}

function renderComposer(
  value: ResearchVoiceContextValue | null,
  isRunning = false,
) {
  return render(
    <ResearchVoiceContext.Provider value={value}>
      <ResearchComposer isRunning={isRunning} onSubmitMessage={vi.fn()} />
    </ResearchVoiceContext.Provider>,
  );
}

describe("ResearchComposer", () => {
  it("starts voice from the Research microphone action", async () => {
    const user = userEvent.setup();
    const start = vi.fn();
    renderComposer(voiceValue({ start }));

    expect(screen.getByRole("textbox")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Start voice mode" }));

    expect(start).toHaveBeenCalledTimes(1);
  });

  it("removes the textbox while voice is active and restores it afterward", () => {
    const inactive = voiceValue();
    const { rerender } = renderComposer(inactive);
    expect(screen.getByRole("textbox")).toBeInTheDocument();

    rerender(
      <ResearchVoiceContext.Provider
        value={voiceValue({ active: true, phase: "listening" })}
      >
        <ResearchComposer isRunning={false} onSubmitMessage={vi.fn()} />
      </ResearchVoiceContext.Provider>,
    );
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.getByText("Listening…")).toBeInTheDocument();

    rerender(
      <ResearchVoiceContext.Provider value={inactive}>
        <ResearchComposer isRunning={false} onSubmitMessage={vi.fn()} />
      </ResearchVoiceContext.Provider>,
    );
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("disables voice while a typed run or typed approval is active", () => {
    const first = renderComposer(voiceValue(), true);
    expect(screen.getByRole("button", { name: "Start voice mode" })).toBeDisabled();
    first.unmount();

    renderComposer(voiceValue({ typedApprovalPending: true }));
    expect(screen.getByRole("button", { name: "Start voice mode" })).toBeDisabled();
  });

  it("keeps text but exposes no microphone outside the Research capability", () => {
    renderComposer(null);

    expect(screen.getByRole("textbox")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Start voice mode" }),
    ).not.toBeInTheDocument();
  });
});
