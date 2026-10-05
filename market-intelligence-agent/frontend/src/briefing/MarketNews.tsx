import { useEffect, useState } from "react";
import type { BriefingNewsItem } from "../lib/api";
import { loadMarketNews, peekMarketNews } from "./briefingData";

function source(url: string) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "Source"; }
}

export function MarketNews({ market }: { market: string }) {
  const [items, setItems] = useState<BriefingNewsItem[] | null>(() => peekMarketNews(market));

  useEffect(() => {
    let active = true;
    setItems(peekMarketNews(market));
    loadMarketNews(market)
      .then((result) => { if (active) setItems(result); })
      .catch(() => { if (active) setItems([]); });
    return () => { active = false; };
  }, [market]);

  return (
    <section className="rounded-2xl border border-terminal-border bg-terminal-panel p-5 shadow-sm">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Live feed</p>
          <h2 className="mt-1 text-xl font-semibold">Latest market news</h2>
        </div>
        <span className="flex items-center gap-1.5 text-xs text-terminal-muted"><span className="h-2 w-2 animate-pulse rounded-full bg-emerald-500" />Live</span>
      </div>
      {items === null ? (
        <div className="space-y-4 py-3">{[1, 2, 3].map((item) => <div key={item} className="animate-pulse border-b border-terminal-border pb-4"><div className="h-3 w-4/5 rounded bg-terminal-border/60" /><div className="mt-2 h-3 w-full rounded bg-terminal-border/40" /></div>)}</div>
      ) : items.length ? items.map((item) => (
        <article key={item.url} className="border-b border-terminal-border py-4 last:border-0">
          <a href={item.url} target="_blank" rel="noreferrer" className="text-sm font-semibold leading-snug hover:text-blue-600 hover:underline">{item.title}</a>
          {item.summary && <p className="mt-1.5 line-clamp-3 text-xs leading-5 text-terminal-muted">{item.summary}</p>}
          <a href={item.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center text-xs font-medium text-blue-600">{source(item.url)} <span className="ml-1">↗</span></a>
        </article>
      )) : <p className="py-4 text-sm text-terminal-muted">No live stories available.</p>}
    </section>
  );
}
