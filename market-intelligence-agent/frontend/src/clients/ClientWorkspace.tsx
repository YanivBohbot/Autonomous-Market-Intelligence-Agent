import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CopilotChat } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "../desk/constants";
import { DeskActivityRail } from "../desk/DeskActivityRail";
import { useIntelligenceSlot } from "../layout/IntelligenceSlot";
import { getClientSummary, type ClientSummary } from "../lib/api";

export function ClientWorkspace() {
  const { id } = useParams<{ id: string }>();
  const clientId = Number(id);
  const [summary, setSummary] = useState<ClientSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intelligencePortal = useIntelligenceSlot(<DeskActivityRail />);

  useEffect(() => {
    setSummary(null);
    setError(null);
    getClientSummary(clientId)
      .then(setSummary)
      .catch(() => setError("Failed to load this client."));
  }, [clientId]);

  return (
    <>
      {intelligencePortal}
      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <div className="border-b border-terminal-border bg-terminal-panel px-4 py-3 font-mono text-sm text-terminal-text">
          {error && <div className="text-terminal-danger">{error}</div>}
          {summary && (
            <div className="flex items-center justify-between">
              <div>
                <span className="font-semibold">{summary.name}</span>
                <span className="ml-2 text-xs text-terminal-muted">
                  {summary.segment} · {summary.risk_profile} · {summary.advisor}
                </span>
              </div>
              {summary.totals ? (
                <span className="text-xs text-terminal-accent">
                  ${summary.totals.market_value.toFixed(2)} ({summary.totals.unrealized_pnl_pct.toFixed(1)}%)
                </span>
              ) : (
                <span className="text-xs text-terminal-muted">No position.</span>
              )}
            </div>
          )}
        </div>
        <CopilotChat
          agentId={MARKET_DESK_AGENT_ID}
          threadId={`clients_${clientId}`}
          className="h-full"
          input={{
            positioning: "static",
            className: "border-t border-terminal-border bg-terminal-panel px-3 py-3",
            textArea:
              "rounded-xl border border-terminal-border bg-terminal-bg px-3.5 py-2.5 font-mono text-sm text-terminal-text placeholder-terminal-muted outline-none transition-colors focus:border-terminal-accent/60",
            sendButton:
              "rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none",
          }}
        />
      </main>
    </>
  );
}
