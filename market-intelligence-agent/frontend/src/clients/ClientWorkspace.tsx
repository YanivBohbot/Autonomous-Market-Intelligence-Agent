import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { DeskView } from "../desk/DeskView";
import { getClientSummary, type ClientSummary } from "../lib/api";

// Delegates the chat entirely to DeskView instead of building a second,
// standalone CopilotChat -- DeskView already owns a correctly-configured
// CopilotKitProvider + HttpAgent (registered for MARKET_DESK_AGENT_ID) +
// messageFilter + useDeskInterrupt/useToolDisplay/DeskActivityRail wiring.
// A hand-rolled CopilotChat here had none of that: useAgent (called by
// DeskActivityRail) requires a CopilotKitProvider above it, which this
// component never provided, so every real render of /clients/:id crashed.
function ClientWorkspaceBody({ clientId }: { clientId: number }) {
  const [summary, setSummary] = useState<ClientSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setSummary(null);
    setError(null);
    getClientSummary(clientId)
      .then((s) => {
        if (active) setSummary(s);
      })
      .catch(() => {
        if (active) setError("Failed to load this client.");
      });
    return () => {
      active = false;
    };
  }, [clientId]);

  if (error) {
    return (
      <main className="flex min-h-0 min-w-0 flex-1 flex-col items-center justify-center gap-3 font-mono text-sm">
        <div className="text-terminal-danger">{error}</div>
        <Link to="/clients" className="text-terminal-accent underline">
          Back to list
        </Link>
      </main>
    );
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <div className="border-b border-terminal-border bg-terminal-panel px-4 py-3 font-mono text-sm text-terminal-text">
        <Link to="/clients" className="mb-2 inline-block text-xs text-terminal-muted hover:text-terminal-accent">
          ← Back to list
        </Link>
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
                {summary.unpriced_tickers.length > 0 && (
                  <span className="ml-1 text-terminal-muted">(excl. {summary.unpriced_tickers.join(", ")})</span>
                )}
              </span>
            ) : summary.unpriced_tickers.length > 0 ? (
              <span className="text-xs text-terminal-danger">Prices unavailable</span>
            ) : (
              <span className="text-xs text-terminal-muted">No position.</span>
            )}
          </div>
        )}
      </div>
      <DeskView threadId={`clients_${clientId}`} />
    </div>
  );
}

export function ClientWorkspace() {
  const { id } = useParams<{ id: string }>();
  // Keyed on id: a route param change (switching clients) does not remount
  // a component by default in react-router, but this page needs a full
  // remount on every client switch -- otherwise DeskActivityRail's single
  // shared agent subscription mixes two clients' activity, and a summary
  // fetch for the client being left can resolve after navigation and paint
  // the wrong client's header.
  return <ClientWorkspaceBody key={id} clientId={Number(id)} />;
}
