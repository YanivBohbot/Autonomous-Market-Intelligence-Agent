import { useEffect, useMemo, useState } from "react";
import type { BriefingInstrument } from "../lib/api";
import { loadMarketIndices, peekMarketIndices } from "./briefingData";
import type { MarketDefinition } from "./markets";
import { InstrumentCard } from "./InstrumentCard";

export function MarketIndexGrid({ market }: { market: MarketDefinition }) {
  const [items, setItems] = useState<BriefingInstrument[] | null>(() => peekMarketIndices(market.id));
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setItems(peekMarketIndices(market.id));
    setFailed(false);
    loadMarketIndices(market.id)
      .then((value) => { if (active) setItems(value); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [market.id]);

  const bySymbol = useMemo(() => new Map(items?.map((item) => [item.symbol, item])), [items]);
  return (
    <section>
      <div className="mb-3 flex items-end justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Live markets</p>
          <h2 className="mt-1 text-xl font-semibold">{market.title} indices</h2>
        </div>
        <span className="text-xs text-terminal-muted">Batched live update</span>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {market.instruments.map((instrument) => (
          <InstrumentCard
            key={`${market.id}:${instrument.symbol}`}
            {...instrument}
            data={bySymbol.get(instrument.symbol)}
            failed={failed || items !== null}
          />
        ))}
      </div>
    </section>
  );
}
