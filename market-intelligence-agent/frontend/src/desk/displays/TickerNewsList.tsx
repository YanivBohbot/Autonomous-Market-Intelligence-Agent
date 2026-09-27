import type { DisplayPayload } from "./types";

export function TickerNewsList({ display }: { display: Extract<DisplayPayload, { type: "ticker_news" }> }) {
  return (
    <div className="flex flex-col gap-2">
      {display.items.map((item, i) => (
        <a
          key={i}
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="rounded-xl border border-terminal-border bg-terminal-panel p-3 font-mono text-xs text-terminal-text hover:border-terminal-accent/40"
        >
          <div className="font-semibold">{item.title}</div>
          {item.summary && <div className="mt-1 text-terminal-muted">{item.summary}</div>}
          <div className="mt-1 text-[10px] text-terminal-muted">{item.source}</div>
        </a>
      ))}
    </div>
  );
}
