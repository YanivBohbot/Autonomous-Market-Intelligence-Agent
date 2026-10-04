import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getClients, type ClientWithHoldings } from "../lib/api";

export function ClientsList() {
  const navigate = useNavigate();
  const [clients, setClients] = useState<ClientWithHoldings[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getClients()
      .then(setClients)
      .catch(() => setError("Failed to load clients."));
  }, []);

  return (
    <div className="space-y-3 font-mono text-sm text-terminal-text">
      {error && (
        <div className="rounded border border-terminal-danger/40 bg-terminal-danger/10 px-3 py-2 text-xs text-terminal-danger">
          {error}
        </div>
      )}
      {clients.map((c) => (
        <button
          key={c.client_id}
          type="button"
          onClick={() => navigate(`/clients/${c.client_id}`)}
          aria-label={c.name}
          className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 text-left transition-colors hover:border-terminal-accent/50"
        >
          <div className="flex items-center justify-between">
            <span className="font-semibold">{c.name}</span>
            <span className="text-xs text-terminal-muted">{c.email} · {c.segment} · {c.risk_profile}</span>
          </div>
          {c.holdings.length > 0 ? (
            <table className="mt-2 w-full text-xs">
              <thead>
                <tr className="text-left text-terminal-muted">
                  <th className="pr-3">Ticker</th>
                  <th className="pr-3">Shares</th>
                  <th>Avg cost</th>
                </tr>
              </thead>
              <tbody>
                {c.holdings.map((h) => (
                  <tr key={h.ticker} className="border-t border-terminal-border/50">
                    <td className="pr-3 py-1">{h.ticker}</td>
                    <td className="pr-3 py-1">{h.shares}</td>
                    <td className="py-1">${h.avg_cost.toFixed(2)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="mt-2 text-xs text-terminal-muted">No holdings.</div>
          )}
        </button>
      ))}
    </div>
  );
}
