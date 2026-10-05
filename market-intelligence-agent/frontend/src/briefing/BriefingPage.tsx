import { useEffect, useState } from "react";
import { ConcentrationAlert } from "../desk/displays/ConcentrationAlert";
import { getBriefing, type BriefingData, type BriefingQuote } from "../lib/api";
import { Sparkline } from "./Sparkline";

function changeColor(change_pct: number) {
  return change_pct >= 0 ? "text-terminal-accent" : "text-terminal-danger";
}

function QuoteCard({ name, price, change_pct }: BriefingQuote) {
  return (
    <div className="rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
      <div className="text-xs text-terminal-muted">{name}</div>
      <div className="font-mono text-sm font-semibold text-terminal-text">{price.toFixed(2)}</div>
      <div className={`text-xs ${changeColor(change_pct)}`}>
        {change_pct >= 0 ? "+" : ""}{change_pct.toFixed(2)}%
      </div>
    </div>
  );
}

export function BriefingPage() {
  const [data, setData] = useState<BriefingData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBriefing()
      .then(setData)
      .catch(() => setError("Failed to load the briefing."));
  }, []);

  if (error) {
    return (
      <main className="flex min-h-0 flex-1 items-center justify-center font-mono text-sm text-terminal-danger">
        {error}
      </main>
    );
  }
  if (!data) {
    return (
      <main className="flex min-h-0 flex-1 items-center justify-center font-mono text-sm text-terminal-muted">
        Loading…
      </main>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-auto p-4 font-mono text-sm text-terminal-text">
      {data.indices.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-semibold text-terminal-muted">Indices</h3>
          <div className="grid grid-cols-4 gap-2">
            {data.indices.map((q) => <QuoteCard key={q.symbol} {...q} />)}
          </div>
        </section>
      )}

      {data.watchlist.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-semibold text-terminal-muted">Watchlist</h3>
          <div className="grid grid-cols-3 gap-2">
            {data.watchlist.map((q) => (
              <div key={q.symbol} className="rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
                <div className="text-xs text-terminal-muted">{q.name}</div>
                <div className="font-mono text-sm font-semibold text-terminal-text">{q.price.toFixed(2)}</div>
                <div className={`text-xs ${changeColor(q.change_pct)}`}>
                  {q.change_pct >= 0 ? "+" : ""}{q.change_pct.toFixed(2)}%
                </div>
                <Sparkline points={q.points} />
              </div>
            ))}
          </div>
        </section>
      )}

      {data.sectors.length > 0 && (
        <section className="flex flex-col gap-1.5">
          <h3 className="text-xs font-semibold text-terminal-muted">Sector performance</h3>
          <div className="flex flex-col gap-1 rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
            {data.sectors.map((s) => (
              <div key={s.symbol} className="flex items-center justify-between">
                <span>{s.name}</span>
                <span className={changeColor(s.change_pct)}>
                  {s.change_pct >= 0 ? "+" : ""}{s.change_pct.toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        </section>
      )}

      <section className="flex flex-col gap-1.5">
        <h3 className="text-xs font-semibold text-terminal-muted">
          Résumé du marché macro-économique et micro-économique
        </h3>
        <div className="whitespace-pre-line rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 text-xs leading-relaxed text-terminal-text">
          {data.narrative}
        </div>
      </section>

      <section className="flex flex-col gap-1.5">
        <h3 className="text-xs font-semibold text-terminal-muted">News</h3>
        {data.news.length > 0 ? (
          <ul className="flex flex-col gap-1 text-xs">
            {data.news.map((n) => (
              <li key={n.url}>
                <a href={n.url} target="_blank" rel="noreferrer" className="text-terminal-accent hover:underline">
                  {n.title}
                </a>
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-xs text-terminal-muted">No news available.</div>
        )}
      </section>

      <section className="flex flex-col gap-1.5">
        <h3 className="text-xs font-semibold text-terminal-muted">Client alerts</h3>
        {data.client_alerts.available ? (
          data.client_alerts.breaches.length > 0 ? (
            <ConcentrationAlert
              display={{
                type: "concentration_alert",
                threshold_pct: data.client_alerts.threshold_pct,
                breaches: data.client_alerts.breaches,
              }}
            />
          ) : (
            <div className="text-xs text-terminal-muted">No concentration breaches.</div>
          )
        ) : (
          <div className="text-xs text-terminal-muted">Alerts unavailable.</div>
        )}
      </section>
    </div>
  );
}
