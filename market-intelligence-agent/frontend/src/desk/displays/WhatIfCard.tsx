import type { DisplayPayload } from "./types";

const usd = (v: number) => v.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function WhatIfCard({ display }: { display: Extract<DisplayPayload, { type: "what_if" }> }) {
  const tickers = [...new Set([...display.before.positions, ...display.after.positions].map((p) => p.ticker))];
  const weight = (side: typeof display.before, t: string) => side.positions.find((p) => p.ticker === t)?.weight_pct ?? 0;
  const resolved = display.breaches_before.filter((t) => !display.breaches_after.includes(t));
  const introduced = display.breaches_after.filter((t) => !display.breaches_before.includes(t));
  const persisting = display.breaches_after.filter((t) => display.breaches_before.includes(t));
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
      <div className="mb-1 font-semibold">What-if · {display.client_name}</div>
      <div className="mb-2 text-terminal-muted">
        Simulation only, nothing executed ·{" "}
        {display.trades.map((t) => `${t.action === "sell" ? "Sell" : "Buy"} ${t.shares} ${t.ticker}`).join(", ")}
      </div>
      <div className="flex flex-col gap-1.5">
        {tickers.map((t) => {
          const b = weight(display.before, t);
          const a = weight(display.after, t);
          return (
            <div key={t} className="grid grid-cols-[4rem_1fr_3.5rem_3.5rem] items-center gap-2">
              <span>{t}</span>
              <div className="flex flex-col gap-0.5">
                <div className="h-1.5 rounded bg-terminal-muted/40" style={{ width: `${b}%` }} />
                <div className="h-1.5 rounded bg-terminal-accent" style={{ width: `${a}%` }} />
              </div>
              <span className="text-right text-terminal-muted">{b.toFixed(1)}%</span>
              <span className="text-right">{a.toFixed(1)}%</span>
            </div>
          );
        })}
      </div>
      <div className="mt-2 flex justify-between border-t border-terminal-border pt-2">
        <span>Value {usd(display.before.totals.market_value)} → {usd(display.after.totals.market_value)}</span>
        <span>{display.cash_delta >= 0 ? "Cash raised" : "Cash needed"} {usd(Math.abs(display.cash_delta))}</span>
      </div>
      {resolved.map((t) => <div key={`r-${t}`} className="mt-1 text-terminal-accent">✓ {t} concentration resolved</div>)}
      {introduced.map((t) => <div key={`n-${t}`} className="mt-1 text-terminal-warn">⚠ {t} becomes a concentration risk</div>)}
      {persisting.map((t) => <div key={`s-${t}`} className="mt-1 text-terminal-warn">⚠ {t} still over 30%</div>)}
    </div>
  );
}
