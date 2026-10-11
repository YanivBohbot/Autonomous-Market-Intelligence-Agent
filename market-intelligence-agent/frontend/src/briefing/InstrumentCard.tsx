import type { BriefingInstrument } from "../lib/api";
import { Sparkline } from "./Sparkline";

function tone(change: number) {
  return change >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400";
}

export function InstrumentCard({
  symbol,
  name,
  compact = false,
  data,
  failed = false,
}: {
  symbol: string;
  name?: string;
  compact?: boolean;
  data?: BriefingInstrument;
  failed?: boolean;
}) {
  if (!data) {
    return (
      <div className={`${compact ? "h-[76px]" : "h-[142px]"} animate-pulse rounded-2xl border border-terminal-border bg-terminal-panel p-4`}>
        <div className="h-3 w-24 rounded bg-terminal-border/60" />
        <div className="mt-4 h-5 w-16 rounded bg-terminal-border/50" />
        {failed && <span className="mt-3 block text-xs text-terminal-danger">Unavailable</span>}
      </div>
    );
  }

  const positive = data.change_pct >= 0;
  return (
    <article className={`group rounded-2xl border border-terminal-border bg-terminal-panel ${compact ? "p-3" : "p-4"} shadow-sm transition hover:-translate-y-0.5 hover:border-blue-400 hover:shadow-md`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-terminal-text">{name ?? data.name}</p>
          <p className="mt-0.5 text-[11px] text-terminal-muted">{symbol}</p>
        </div>
        <span className={`rounded-full px-2 py-1 text-xs font-semibold tabular-nums ${positive ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300" : "bg-red-50 text-red-700 dark:bg-red-950/50 dark:text-red-300"}`}>
          {positive ? "+" : ""}{data.change_pct.toFixed(2)}%
        </span>
      </div>
      <div className="mt-3 flex items-end justify-between gap-3">
        <span className="text-lg font-semibold tabular-nums">{data.price.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>
        <div className={compact ? "w-24" : "w-32"}>
          <Sparkline points={data.points} color={positive ? "#059669" : "#dc2626"} />
        </div>
      </div>
      {!compact && <p className={`mt-1 text-xs ${tone(data.change_pct)}`}>{positive ? "Market is up today" : "Market is down today"}</p>}
    </article>
  );
}
