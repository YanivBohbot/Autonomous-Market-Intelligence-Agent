import { useEffect, useMemo, useState } from "react";
import type { BriefingInstrument } from "../lib/api";
import { loadSectors, peekSectors } from "./briefingData";
import { InstrumentCard } from "./InstrumentCard";
import { SECTORS } from "./markets";

export function SectorPanel() {
  const [items, setItems] = useState<BriefingInstrument[] | null>(() => peekSectors());
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    loadSectors()
      .then((value) => { if (active) setItems(value); })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, []);

  const bySymbol = useMemo(() => new Map(items?.map((item) => [item.symbol, item])), [items]);
  return (
    <section className="rounded-2xl border border-terminal-border bg-terminal-panel p-4 shadow-sm">
      <div className="mb-3">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Capital sectors</p>
        <h2 className="mt-1 text-lg font-semibold">Sector performance</h2>
      </div>
      <div className="space-y-2">
        {SECTORS.map((sector) => (
          <InstrumentCard
            key={sector.symbol}
            {...sector}
            compact
            data={bySymbol.get(sector.symbol)}
            failed={failed || items !== null}
          />
        ))}
      </div>
    </section>
  );
}
