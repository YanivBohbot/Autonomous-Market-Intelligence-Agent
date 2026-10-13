import type { DisplayPayload, WatchlistRow } from "./types";

const BADGE: Record<WatchlistRow["status"], { label: string; cls: string }> = {
  triggered: { label: "Triggered", cls: "bg-red-500/15 text-red-400" },
  near: { label: "Near", cls: "bg-amber-500/15 text-amber-400" },
  watching: { label: "Watching", cls: "bg-terminal-muted/15 text-terminal-muted" },
};

export function WatchlistAlertsCard({ display }: { display: Extract<DisplayPayload, { type: "watchlist_alerts" }> }) {
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
      <div className="mb-2 font-semibold">Watchlist alerts · near = within {display.near_pct}%</div>
      <div className="flex flex-col gap-1.5">
        {display.rows.map((r) => (
          <div key={`${r.client}-${r.ticker}`} className="grid grid-cols-[5.5rem_1fr_auto] items-center gap-2">
            <span className={`rounded px-1.5 py-0.5 text-center text-[10px] font-semibold ${BADGE[r.status].cls}`}>{BADGE[r.status].label}</span>
            <span>
              {r.client} — {r.ticker} ${r.price.toFixed(2)}{" "}
              <span className="text-terminal-muted">({r.direction} ${r.alert_price.toFixed(2)})</span>
            </span>
            <span className="text-right">{`${r.distance_pct > 0 ? "+" : ""}${r.distance_pct.toFixed(1)}%`}</span>
          </div>
        ))}
      </div>
      {display.unpriced.length > 0 && <div className="mt-2 text-terminal-muted">No price for {display.unpriced.join(", ")}</div>}
    </div>
  );
}
