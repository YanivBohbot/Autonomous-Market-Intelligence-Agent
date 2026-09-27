import type { DisplayPayload } from "./types";

export function TickerInfoCard({ display }: { display: Extract<DisplayPayload, { type: "ticker_info" }> }) {
  return (
    <div className="rounded-xl border border-terminal-border bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
      <div className="flex items-baseline justify-between">
        <span className="font-semibold">{display.name}</span>
        <span className="text-terminal-muted">{display.ticker}</span>
      </div>
      <div className="mt-1 text-lg text-terminal-accent">
        ${display.current_price.toFixed(2)} <span className="text-xs text-terminal-muted">{display.currency}</span>
      </div>
      {(display.sector || display.industry) && (
        <div className="mt-1 text-terminal-muted">
          {[display.sector, display.industry].filter(Boolean).join(" · ")}
        </div>
      )}
      {(display.fifty_two_week_low != null && display.fifty_two_week_high != null) && (
        <div className="mt-1 text-terminal-muted">
          52w range: {display.fifty_two_week_low.toFixed(2)} – {display.fifty_two_week_high.toFixed(2)}
        </div>
      )}
    </div>
  );
}
