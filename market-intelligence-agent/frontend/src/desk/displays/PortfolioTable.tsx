import type { DisplayPayload } from "./types";

const money = (n: number) =>
  (n < 0 ? "-" : "") + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function PortfolioTable({ display }: { display: Extract<DisplayPayload, { type: "portfolio_table" }> }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-terminal-border bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
      <table className="w-full">
        <thead>
          <tr className="text-left text-terminal-muted">
            <th className="pb-1.5 pr-3">Ticker</th>
            <th className="pb-1.5 pr-3">Shares</th>
            <th className="pb-1.5 pr-3">Value</th>
            <th className="pb-1.5 pr-3">P&amp;L</th>
            <th className="pb-1.5">Weight</th>
          </tr>
        </thead>
        <tbody>
          {display.positions.map((p) => (
            <tr key={p.ticker} className="border-t border-terminal-border/50">
              <td className="py-1 pr-3 font-semibold">{p.ticker}</td>
              <td className="py-1 pr-3">{p.shares}</td>
              <td className="py-1 pr-3">{money(p.market_value)}</td>
              <td className={`py-1 pr-3 ${p.unrealized_pnl < 0 ? "text-terminal-danger" : "text-terminal-accent"}`}>
                {money(p.unrealized_pnl)}
              </td>
              <td className="py-1">{p.weight_pct.toFixed(2)}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 border-t border-terminal-border pt-2 text-terminal-accent">
        Total: {money(display.totals.market_value)}
      </div>
    </div>
  );
}
