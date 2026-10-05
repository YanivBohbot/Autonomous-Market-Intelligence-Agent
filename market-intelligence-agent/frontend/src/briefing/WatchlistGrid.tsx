import { useEffect, useMemo, useState } from "react";
import type { BriefingInstrument } from "../lib/api";
import { loadWatchlist, peekWatchlist } from "./briefingData";
import { InstrumentCard } from "./InstrumentCard";
import { WATCHLIST } from "./markets";

export function WatchlistGrid() {
  const [items, setItems] = useState<BriefingInstrument[] | null>(() => peekWatchlist());
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    loadWatchlist()
      .then((value) => { if (active) setItems(value); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);

  const bySymbol = useMemo(() => new Map(items?.map((item) => [item.symbol, item])), [items]);
  return (
    <section>
      <div className="mb-3">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Mega-cap watchlist</p>
        <h2 className="mt-1 text-xl font-semibold">Companies to watch</h2>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {WATCHLIST.map((symbol) => (
          <InstrumentCard
            key={symbol}
            symbol={symbol}
            data={bySymbol.get(symbol)}
            failed={failed || items !== null}
          />
        ))}
      </div>
    </section>
  );
}
