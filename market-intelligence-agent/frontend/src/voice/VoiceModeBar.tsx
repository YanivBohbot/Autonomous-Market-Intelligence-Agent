import { useEffect, useState } from "react";
import type { VoicePhase } from "./types";

const PHASE_LABELS: Record<VoicePhase, string> = {
  connecting: "Connecting…",
  listening: "Listening…",
  analyzing: "Analyzing…",
  speaking: "Speaking…",
  approval_required: "Approval required",
  disconnected: "Voice mode",
  error: "Voice unavailable",
};

function usePrefersReducedMotion() {
  const [reduced, setReduced] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const query = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = (event: MediaQueryListEvent) => setReduced(event.matches);
    query.addEventListener?.("change", onChange);
    return () => query.removeEventListener?.("change", onChange);
  }, []);

  return reduced;
}

function Waveform({ reduced }: { reduced: boolean }) {
  return (
    <span className="flex h-7 items-center gap-1" aria-hidden="true">
      {[0, 1, 2, 3, 4].map((index) => (
        <span
          key={index}
          data-testid="voice-wave-segment"
          className="w-1 rounded-full bg-blue-600 dark:bg-blue-400"
          style={{
            height: `${12 + (index % 3) * 5}px`,
            animation: reduced
              ? "none"
              : "voice-wave 900ms ease-in-out infinite alternate",
            animationDelay: `${index * 90}ms`,
          }}
        />
      ))}
    </span>
  );
}

export function VoiceModeBar({
  phase,
  onEnd,
}: {
  phase: VoicePhase;
  onEnd: () => void;
}) {
  const reduced = usePrefersReducedMotion();
  const showWaveform = phase === "listening" || phase === "speaking";
  const needsApproval = phase === "approval_required";

  return (
    <div className="border-t border-terminal-border bg-terminal-panel px-3 py-3">
      <div className="flex min-h-16 items-center gap-3 rounded-2xl border border-blue-200 bg-blue-50/70 px-4 py-3 shadow-sm dark:border-blue-500/30 dark:bg-blue-500/10">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm dark:bg-blue-500">
          {showWaveform ? (
            <Waveform reduced={reduced} />
          ) : (
            <span
              aria-hidden="true"
              className={`h-3 w-3 rounded-full bg-white ${
                phase === "analyzing" && !reduced ? "animate-pulse" : ""
              }`}
            />
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div
            role="status"
            aria-live="polite"
            className="text-sm font-semibold text-terminal-text"
          >
            {PHASE_LABELS[phase]}
          </div>
          <p className="mt-0.5 text-xs text-terminal-muted">
            {needsApproval
              ? "Say Approve or Reject · or use the card"
              : "Voice mode · Text input locked"}
          </p>
          {needsApproval && (
            <p className="mt-0.5 text-[11px] text-terminal-muted">
              Voice mode · Text input locked
            </p>
          )}
        </div>

        <button
          type="button"
          onClick={onEnd}
          className="shrink-0 rounded-xl border border-terminal-border bg-terminal-panel px-3 py-2 text-xs font-semibold text-terminal-text transition-colors hover:border-blue-400 hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500/40 dark:hover:text-blue-300"
        >
          End voice mode
        </button>
      </div>
    </div>
  );
}
