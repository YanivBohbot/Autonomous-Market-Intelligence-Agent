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
import { PageHeader } from "../ui/PageHeader";
import { StatusBadge } from "../ui/StatusBadge";

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
      <div className="mb-7">
        <PageHeader
          eyebrow="Market intelligence"
          title="Global markets briefing"
          description="Live indices, trend charts, market context and actionable signals — refreshed independently for faster navigation."
          actions={(
            <StatusBadge tone="success">
              <span className="mr-2 inline-block h-2 w-2 animate-pulse rounded-full bg-emerald-500" aria-hidden="true" />
              Live data
            </StatusBadge>
          )}
        >
          <MarketTabs markets={MARKETS} active={marketId} onChange={setMarketId} onPrefetch={prefetchMarket} />
        </PageHeader>
      </div>

      <div className="space-y-7">
        <MarketIndexGrid market={market} />
        <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_360px]"><div className="space-y-6"><MarketSummary market={marketId} /><MarketNews market={marketId} /><WatchlistGrid /><ClientAlertsPanel /></div><aside className="space-y-6"><SectorPanel /><MarketMovers market={marketId} /></aside></div>
      </div>
    </div>
  </main>;
}
