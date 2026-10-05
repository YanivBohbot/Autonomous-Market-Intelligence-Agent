import { useEffect, useMemo, useState } from "react";
import { ClientAlertsPanel } from "./ClientAlertsPanel";
import { MarketIndexGrid } from "./MarketIndexGrid";
import { MarketMovers } from "./MarketMovers";
import { MarketNews } from "./MarketNews";
import { MarketSummary } from "./MarketSummary";
import { MarketTabs } from "./MarketTabs";
import { MARKETS } from "./markets";
import { SectorPanel } from "./SectorPanel";
import { WatchlistGrid } from "./WatchlistGrid";
import { loadMarketIndices, prefetchMarket } from "./briefingData";

export function BriefingPage() {
  const [marketId, setMarketId] = useState("us");
  const market = useMemo(() => MARKETS.find((item) => item.id === marketId) ?? MARKETS[0], [marketId]);
  useEffect(() => {
    let active = true;
    void (async () => {
      try { await loadMarketIndices("us"); } catch { return; }
      for (const item of MARKETS) {
        if (!active || item.id === "us") continue;
        try { await loadMarketIndices(item.id); } catch { /* a regional feed may be temporarily unavailable */ }
      }
    })();
    return () => { active = false; };
  }, []);
  return <main className="min-h-0 min-w-0 flex-1 overflow-auto bg-terminal-bg font-sans text-terminal-text">
    <div className="mx-auto max-w-[1500px] px-4 py-6 md:px-7">
      <header className="mb-7 rounded-3xl border border-blue-100 bg-gradient-to-br from-blue-50 via-white to-emerald-50 p-6 shadow-sm dark:border-terminal-border dark:from-blue-950/40 dark:via-terminal-panel dark:to-emerald-950/30">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4"><div><p className="text-xs font-bold uppercase tracking-[0.22em] text-blue-600">Market intelligence</p><h1 className="mt-2 text-3xl font-semibold tracking-tight">Global markets briefing</h1><p className="mt-2 max-w-2xl text-sm text-terminal-muted">Live indices, trend charts, market context and actionable signals — refreshed independently for faster navigation.</p></div><div className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1.5 text-xs font-semibold text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-300"><span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500" />Live data</div></div>
        <MarketTabs markets={MARKETS} active={marketId} onChange={setMarketId} onPrefetch={prefetchMarket} />
      </header>

      <div className="space-y-7">
        <MarketIndexGrid market={market} />
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]"><div className="space-y-6"><MarketSummary market={marketId} /><MarketNews market={marketId} /><WatchlistGrid /><ClientAlertsPanel /></div><aside className="space-y-6"><SectorPanel /><MarketMovers market={marketId} /></aside></div>
      </div>
    </div>
  </main>;
}
