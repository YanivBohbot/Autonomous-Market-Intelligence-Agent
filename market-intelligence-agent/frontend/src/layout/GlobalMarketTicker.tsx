import { useEffect, useState } from "react";
import { getMarketTicker, type MarketTickerItem } from "../lib/api";
import { Skeleton } from "../ui/FeedbackStates";

const POLL_INTERVAL_MS = 60_000;

function formatPrice(price: number): string {
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits: price < 10 ? 4 : 2,
    maximumFractionDigits: price < 10 ? 4 : 2,
  }).format(price);
}

function changeLabel(change: number): string {
  if (change > 0) return `up ${change.toFixed(2)}%`;
  if (change < 0) return `down ${Math.abs(change).toFixed(2)}%`;
  return "unchanged 0.00%";
}

function TickerItems({ items }: { items: MarketTickerItem[] }) {
  return (
    <>
      {items.map((item) => {
        const tone = item.change_pct > 0
          ? "text-emerald-600 dark:text-emerald-400"
          : item.change_pct < 0
            ? "text-red-600 dark:text-red-400"
            : "text-terminal-muted";

        return (
          <li key={item.symbol} className="flex shrink-0 items-center gap-2 px-5 py-2 text-xs">
            <span className="font-semibold text-terminal-text">{item.name}</span>
            <span className="font-mono tabular-nums text-terminal-muted">{formatPrice(item.price)}</span>
            <span className={`font-semibold tabular-nums ${tone}`}>{changeLabel(item.change_pct)}</span>
          </li>
        );
      })}
    </>
  );
}

export function GlobalMarketTicker() {
  const [items, setItems] = useState<MarketTickerItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  useEffect(() => {
    let active = true;

    const load = async () => {
      try {
        const response = await getMarketTicker();
        if (!active) return;
        if (response.items.length > 0) {
          setItems(response.items);
          setUpdatedAt(new Date());
          setUnavailable(false);
        } else {
          setUnavailable(true);
        }
      } catch {
        if (active) setUnavailable(true);
      } finally {
        if (active) setLoading(false);
      }
    };

    void load();
    const intervalId = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_INTERVAL_MS);
    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      active = false;
      window.clearInterval(intervalId);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, []);

  if (loading) {
    return (
      <section aria-label="Global market ticker" className="border-b border-terminal-border bg-surface-elevated px-4 py-2">
        <Skeleton className="h-5 w-full" label="Loading market feed" />
      </section>
    );
  }

  if (items.length === 0 && unavailable) {
    return (
      <section aria-label="Global market ticker" className="border-b border-terminal-border bg-surface-elevated px-4 py-2 text-center text-xs text-terminal-muted">
        Market feed unavailable
      </section>
    );
  }

  return (
    <section aria-label="Global market ticker" className="market-ticker flex items-stretch overflow-hidden border-b border-terminal-border bg-surface-elevated">
      <div className="min-w-0 flex-1 overflow-hidden" aria-live="off">
        <div data-testid="ticker-track" className="market-ticker-track flex">
          <ul aria-label="World markets" className="flex shrink-0 divide-x divide-terminal-border/70">
            <TickerItems items={items} />
          </ul>
          <ul data-testid="ticker-copy" aria-hidden="true" className="market-ticker-copy flex shrink-0 divide-x divide-terminal-border/70">
            <TickerItems items={items} />
          </ul>
        </div>
      </div>
      {updatedAt && (
        <p className="relative z-10 flex shrink-0 items-center border-l border-terminal-border bg-surface-elevated px-3 text-[10px] uppercase tracking-wide text-terminal-muted">
          Updated {updatedAt.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
        </p>
      )}
    </section>
  );
}
