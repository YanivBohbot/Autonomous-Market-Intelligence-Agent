import type { MarketDefinition } from "./markets";

export function MarketTabs({ markets, active, onChange, onPrefetch }: { markets: MarketDefinition[]; active: string; onChange: (id: string) => void; onPrefetch?: (id: string) => void }) {
  return <nav aria-label="Market regions" className="flex gap-2 overflow-x-auto pb-1">
    {markets.map((market) => <button key={market.id} type="button" onPointerEnter={() => onPrefetch?.(market.id)} onFocus={() => onPrefetch?.(market.id)} onClick={() => onChange(market.id)} className={`whitespace-nowrap rounded-full border px-4 py-2 text-sm font-medium transition-colors ${active === market.id ? "border-blue-600 bg-blue-600 text-white shadow-sm" : "border-terminal-border bg-terminal-panel text-terminal-muted hover:border-blue-400 hover:text-terminal-text"}`}>{market.label}</button>)}
  </nav>;
}
