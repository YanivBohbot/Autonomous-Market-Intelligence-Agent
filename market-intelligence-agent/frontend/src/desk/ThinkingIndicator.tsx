import { useEffect, useState } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "./constants";

const SPECIALIST_LABELS: Record<string, string> = {
  rag_agent: "Searching the knowledge base...",
  finance_agent: "Checking market data...",
  portfolio_agent: "Analyzing the portfolio...",
  browser_agent: "Browsing the web...",
  email_agent: "Preparing the email...",
  filesystem_agent: "Reading files...",
  memory_agent: "Checking memory...",
};

const GENERIC_LABEL = "Thinking...";

// Mirrors DeskActivityRail's subscribe pattern, but derives a single
// human-readable "what's happening right now" line instead of a full log.
// Rendered by DeskView inline in CopilotChat's own message list (via the
// messageView slot), right where the assistant's answer will appear, so
// it reads as "the AI is working on this" rather than a separate widget.
// Visible from the run starting until real content (the assistant's own
// answer) starts streaming.
export function ThinkingIndicator() {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const [label, setLabel] = useState<string | null>(null);

  useEffect(() => {
    const sub = agent.subscribe({
      onEvent: ({ event }) => {
        const e = event as { type: string; stepName?: string; toolCallName?: string };
        switch (e.type) {
          case "RUN_STARTED":
            setLabel(GENERIC_LABEL);
            break;
          case "STEP_STARTED":
            setLabel(SPECIALIST_LABELS[String(e.stepName)] ?? GENERIC_LABEL);
            break;
          case "TOOL_CALL_START":
            setLabel(`Running ${e.toolCallName}...`);
            break;
          case "TEXT_MESSAGE_CONTENT":
          case "RUN_FINISHED":
          case "RUN_ERROR":
            setLabel(null);
            break;
        }
      },
      onRunFailed: () => setLabel(null),
    });
    return () => sub.unsubscribe();
  }, [agent]);

  if (!label) return null;

  return (
    <div className="flex items-center gap-2 rounded-xl border border-terminal-border bg-terminal-panel px-3 py-2 font-mono text-xs text-terminal-accent">
      <span className="flex gap-0.5">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-terminal-accent [animation-delay:-0.3s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-terminal-accent [animation-delay:-0.15s]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-terminal-accent" />
      </span>
      {label}
    </div>
  );
}
