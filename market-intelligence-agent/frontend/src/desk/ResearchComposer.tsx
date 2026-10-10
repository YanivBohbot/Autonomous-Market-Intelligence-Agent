import {
  CopilotChatInput,
  type CopilotChatInputProps,
} from "@copilotkit/react-core/v2";
import type { ButtonHTMLAttributes } from "react";
import { useResearchVoiceContext } from "../voice/ResearchVoiceContext";
import { VoiceModeBar } from "../voice/VoiceModeBar";

function HiddenVoiceAction() {
  return null;
}

function VoiceStartButton({
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      type="button"
      aria-label="Start voice mode"
      title="Start voice mode"
      className={`inline-flex h-10 w-10 items-center justify-center rounded-xl border border-terminal-border bg-terminal-panel text-terminal-muted transition-colors hover:border-blue-400 hover:text-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-40 dark:hover:text-blue-300 ${className ?? ""}`}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        className="h-5 w-5"
      >
        <rect x="8" y="3" width="8" height="12" rx="4" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" />
      </svg>
    </button>
  );
}

export function ResearchComposer(props: CopilotChatInputProps) {
  const voice = useResearchVoiceContext();

  if (voice?.active) {
    return <VoiceModeBar phase={voice.phase} onEnd={voice.end} />;
  }

  const voiceAvailable = Boolean(voice?.enabled);
  const voiceDisabled =
    !voiceAvailable || Boolean(props.isRunning) || Boolean(voice?.typedApprovalPending);
  const StartVoiceAction = voiceAvailable
    ? (buttonProps: ButtonHTMLAttributes<HTMLButtonElement>) => (
        <VoiceStartButton {...buttonProps} disabled={voiceDisabled} />
      )
    : HiddenVoiceAction;

  return (
    <CopilotChatInput
      {...props}
      positioning="static"
      showDisclaimer={false}
      className="border-t border-terminal-border bg-terminal-panel px-3 py-3"
      textArea="rounded-xl border border-terminal-border bg-terminal-bg px-3.5 py-2.5 font-mono text-sm text-terminal-text placeholder-terminal-muted outline-none transition-colors focus:border-terminal-accent/60"
      sendButton="rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
      startTranscribeButton={StartVoiceAction}
      onStartTranscribe={voiceAvailable ? voice?.start : undefined}
    />
  );
}
