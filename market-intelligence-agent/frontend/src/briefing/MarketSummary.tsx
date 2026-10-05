import { useEffect, useState } from "react";
import type { BriefingInstrument } from "../lib/api";
import {
  loadMarketIndices,
  loadMarketNarrative,
  peekMarketNarrative,
} from "./briefingData";

function instantSummary(items: BriefingInstrument[]) {
  if (!items.length) return "";
  const sorted = [...items].sort((left, right) => right.change_pct - left.change_pct);
  const average = items.reduce((total, item) => total + item.change_pct, 0) / items.length;
  const leader = sorted[0];
  const laggard = sorted[sorted.length - 1];
  const direction = average >= 0 ? "positive" : "negative";
  return `The session has a ${direction} bias, with the monitored indices averaging ${average >= 0 ? "+" : ""}${average.toFixed(2)}%. ${leader.name} leads at ${leader.change_pct >= 0 ? "+" : ""}${leader.change_pct.toFixed(2)}%, while ${laggard.name} trails at ${laggard.change_pct >= 0 ? "+" : ""}${laggard.change_pct.toFixed(2)}%. The extended market analysis is updating in the background.`;
}

export function MarketSummary({ market }: { market: string }) {
  const [text, setText] = useState(() => peekMarketNarrative(market) ?? "");
  const [expanded, setExpanded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let finalNarrativeLoaded = Boolean(peekMarketNarrative(market));
    setText(peekMarketNarrative(market) ?? "");
    setExpanded(false);
    setFailed(false);

    loadMarketIndices(market).then((items) => {
      if (active && !finalNarrativeLoaded) setText(instantSummary(items));
    }).catch(() => undefined);

    loadMarketNarrative(market)
      .then((result) => {
        finalNarrativeLoaded = true;
        if (active) setText(result);
      })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [market]);

  const visible = !expanded && text.length > 520 ? `${text.slice(0, 520)}…` : text;
  return (
    <section className="rounded-2xl border border-terminal-border bg-terminal-panel p-5 shadow-sm">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Daily intelligence</p>
          <h2 className="mt-1 text-xl font-semibold">Macro & micro market summary</h2>
        </div>
        {text.length > 520 && <button type="button" onClick={() => setExpanded((value) => !value)} className="rounded-full border border-terminal-border px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/30">{expanded ? "Show less ↑" : "Read more ↓"}</button>}
      </div>
      {text ? <p className="whitespace-pre-line text-sm leading-7 text-terminal-text">{visible}</p> : failed ? <p className="text-sm text-terminal-danger">Summary unavailable.</p> : <div className="space-y-2 animate-pulse"><div className="h-3 rounded bg-terminal-border/60" /><div className="h-3 w-11/12 rounded bg-terminal-border/50" /><div className="h-3 w-4/5 rounded bg-terminal-border/40" /></div>}
    </section>
  );
}
