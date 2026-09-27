import type { DisplayPayload } from "./types";

export function ConcentrationAlert({ display }: { display: Extract<DisplayPayload, { type: "concentration_alert" }> }) {
  return (
    <div className="rounded-xl border border-terminal-warn/40 bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
      <div className="mb-2 text-terminal-warn">Concentration &gt; {display.threshold_pct}%</div>
      <div className="flex flex-col gap-1.5">
        {display.breaches.map((b, i) => (
          <div key={i} className="flex justify-between">
            <span>{b.label} — {b.ticker}</span>
            <span className="text-terminal-warn">{b.weight_pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
