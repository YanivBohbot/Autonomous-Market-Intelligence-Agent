import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { VoiceModeBar } from "./VoiceModeBar";
import type { VoicePhase } from "./types";

const phaseLabels: Array<[VoicePhase, string]> = [
  ["connecting", "Connecting…"],
  ["listening", "Listening…"],
  ["analyzing", "Analyzing…"],
  ["speaking", "Speaking…"],
  ["approval_required", "Approval required"],
];

describe("VoiceModeBar", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it.each(phaseLabels)("announces the %s phase in English", (phase, label) => {
    render(<VoiceModeBar phase={phase} onEnd={vi.fn()} />);

    expect(screen.getByRole("status")).toHaveTextContent(label);
    expect(screen.getByText("Voice mode · Text input locked")).toBeInTheDocument();
    expect(screen.queryByText(/finance|portfolio|rag|browser/i)).not.toBeInTheDocument();
  });

  it("shows five animated columns only for listening and speaking", () => {
    const { rerender } = render(
      <VoiceModeBar phase="listening" onEnd={vi.fn()} />,
    );
    expect(screen.getAllByTestId("voice-wave-segment")).toHaveLength(5);

    rerender(<VoiceModeBar phase="speaking" onEnd={vi.fn()} />);
    expect(screen.getAllByTestId("voice-wave-segment")).toHaveLength(5);

    rerender(<VoiceModeBar phase="analyzing" onEnd={vi.fn()} />);
    expect(screen.queryAllByTestId("voice-wave-segment")).toHaveLength(0);
  });

  it("offers the spoken and visual approval paths", () => {
    render(<VoiceModeBar phase="approval_required" onEnd={vi.fn()} />);

    expect(
      screen.getByText("Say Approve or Reject · or use the card"),
    ).toBeInTheDocument();
  });

  it("ends voice mode from the explicit action", () => {
    const onEnd = vi.fn();
    render(<VoiceModeBar phase="listening" onEnd={onEnd} />);

    fireEvent.click(screen.getByRole("button", { name: "End voice mode" }));

    expect(onEnd).toHaveBeenCalledTimes(1);
  });

  it("removes waveform animation when reduced motion is requested", () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn().mockReturnValue({
        matches: true,
        media: "(prefers-reduced-motion: reduce)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }),
    );

    render(<VoiceModeBar phase="listening" onEnd={vi.fn()} />);

    for (const segment of screen.getAllByTestId("voice-wave-segment")) {
      expect(segment).toHaveStyle({ animation: "none" });
    }
  });
});
