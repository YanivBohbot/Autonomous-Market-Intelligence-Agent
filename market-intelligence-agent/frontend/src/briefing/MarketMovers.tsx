import { useEffect, useState } from "react";
import type { BriefingData, BriefingQuote } from "../lib/api";
import { loadMarketMovers, peekMarketMovers } from "./briefingData";

type Movers = NonNullable<BriefingData["movers"]>;

function MoversList({ title, data }: { title: string; data: BriefingQuote[] | null }) {
  return (
    <section className="rounded-2xl border border-terminal-border bg-terminal-panel p-4 shadow-sm">
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      {data === null ? (
        <div className="space-y-3 animate-pulse">{[1, 2, 3].map((row) => <div key={row} className="h-4 rounded bg-terminal-border/50" />)}</div>
      ) : data.length ? data.map((quote) => (
        <div key={quote.symbol} className="flex items-center justify-between border-b border-terminal-border py-2.5 last:border-0">
          <div><p className="text-xs font-semibold">{quote.symbol}</p><p className="max-w-32 truncate text-[11px] text-terminal-muted">{quote.name}</p></div>
          <div className="text-right"><p className="text-xs font-medium tabular-nums">{quote.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}</p><p className={`text-xs font-semibold tabular-nums ${quote.change_pct >= 0 ? "text-emerald-600" : "text-red-600"}`}>{quote.change_pct >= 0 ? "+" : ""}{quote.change_pct.toFixed(2)}%</p></div>
        </div>
      )) : <p className="text-xs text-terminal-muted">Unavailable.</p>}
    </section>
  );
}

export function MarketMovers({ market }: { market: string }) {
  const [data, setData] = useState<Movers | null>(() => peekMarketMovers(market));
  useEffect(() => {
    let active = true;
    setData(peekMarketMovers(market));
    loadMarketMovers(market)
      .then((result) => { if (active) setData(result); })
      .catch(() => { if (active) setData({ most_active: [], gainers: [], losers: [] }); });
    return () => { active = false; };
  }, [market]);
  return <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-1"><MoversList title="Most active" data={data?.most_active ?? null} /><MoversList title="Top gainers" data={data?.gainers ?? null} /><MoversList title="Top losers" data={data?.losers ?? null} /></div>;
}
