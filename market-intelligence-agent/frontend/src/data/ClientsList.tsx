import { useEffect, useState } from "react";
import { getClients, type ClientWithHoldings } from "../lib/api";

export function ClientsList() {
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
        <div key={c.client_id} className="rounded-xl border border-terminal-border bg-terminal-panel p-3">
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
        </div>
      ))}
    </div>
  );
}
