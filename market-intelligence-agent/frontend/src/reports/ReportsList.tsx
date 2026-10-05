import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getClients, type ClientWithHoldings } from "../lib/api";

// Deliberately not ClientsList (chantier 2): live QA showed the two
// sections looking identical was confusing -- a holdings table makes
// sense for "browse clients," not for "pick a client to report on."
export function ReportsList() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<ClientWithHoldings[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getClients()
      .then(setClients)
      .catch(() => setError("Failed to load clients."));
  }, []);

  return (
    <div className="space-y-2 font-mono text-sm text-terminal-text">
      {error && (
        <div className="rounded border border-terminal-danger/40 bg-terminal-danger/10 px-3 py-2 text-xs text-terminal-danger">
          {error}
        </div>
      )}
      {clients.map((c) => (
        <button
          key={c.client_id}
          type="button"
          onClick={() => navigate(`/reports/${c.client_id}`)}
          aria-label={c.name}
          className="flex w-full items-center justify-between rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 text-left transition-colors hover:border-terminal-accent/50"
        >
          <div>
            <span className="font-semibold">{c.name}</span>
            <span className="ml-2 text-xs text-terminal-muted">
              {c.segment} · {c.risk_profile} · {c.advisor}
            </span>
          </div>
          <span className="shrink-0 rounded-lg border border-terminal-accent/40 px-3 py-1.5 text-xs text-terminal-accent">
            View Report
          </span>
        </button>
      ))}
    </div>
  );
}
