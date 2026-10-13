// Clickable holdings chips on the client workspace: the selected one is
// shared with the agent (useAgentContext) so "explain this position" works.
export function HoldingsStrip({
  positions,
  selected,
  onSelect,
}: {
  positions: { ticker: string; weight_pct: number }[];
  selected: string | null;
  onSelect: (ticker: string | null) => void;
}) {
  if (positions.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-2" aria-label="Holdings">
      {positions.map((p) => {
        const on = p.ticker === selected;
        return (
          <button
            key={p.ticker}
            type="button"
            aria-pressed={on}
            onClick={() => onSelect(on ? null : p.ticker)}
            className={`rounded-full border px-3 py-1 font-mono text-xs transition-colors ${
              on
                ? "border-terminal-accent bg-terminal-accent/15 text-terminal-text"
                : "border-terminal-border text-terminal-muted hover:text-terminal-text"
            }`}
          >
            {p.ticker} · {p.weight_pct.toFixed(1)}%
          </button>
        );
      })}
    </div>
  );
}
