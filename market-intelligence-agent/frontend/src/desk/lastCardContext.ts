import { parseDisplay } from "./displays/parseDisplay";
import type { DisplayPayload } from "./displays/types";

function keyFields(d: DisplayPayload): Record<string, unknown> | null {
  switch (d.type) {
    case "company_comparison": return { card: d.type, symbols: d.companies.map((c) => c.symbol), period: d.period };
    case "what_if": return { card: d.type, client: d.client_name, trades: d.trades.map((t) => `${t.action} ${t.shares} ${t.ticker}`) };
    case "watchlist_alerts": return { card: d.type, clients: [...new Set(d.rows.map((r) => r.client))] };
    case "portfolio_table": return { card: d.type, tickers: d.positions.map((p) => p.ticker) };
    case "ticker_info": return { card: d.type, ticker: d.ticker };
    case "price_chart": return { card: d.type, ticker: d.ticker };
    default: return null;
  }
}

// The newest rich card in the chat, so "add AMD" / "now 25% instead" has a referent.
export function lastCardContext(messages: { role?: string; content?: unknown }[]): string | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role !== "tool") continue;
    const env = parseDisplay(messages[i].content);
    for (const d of env?.displays ?? []) {
      const fields = keyFields(d);
      if (fields) return JSON.stringify(fields);
    }
  }
  return null;
}
