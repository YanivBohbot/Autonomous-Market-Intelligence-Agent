import { useEffect, useState } from "react";
import { getBriefingClientAlerts, type BriefingData } from "../lib/api";

type ClientAlerts = BriefingData["client_alerts"];

const money = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});

function AlertIcon({ safe = false }: { safe?: boolean }) {
  return (
    <span
      className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl ${
        safe
          ? "bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-300"
          : "bg-amber-50 text-amber-600 dark:bg-amber-950/50 dark:text-amber-300"
      }`}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" fill="none" className="h-5 w-5" stroke="currentColor" strokeWidth="1.8">
        {safe ? (
          <path strokeLinecap="round" strokeLinejoin="round" d="m7.5 12 3 3 6-7m4.5 4a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z" />
        ) : (
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9.3 3.02L14.05 3.2a2.37 2.37 0 0 0-4.1 0L2.7 15.77A2.37 2.37 0 0 0 4.75 19.3h14.5a2.37 2.37 0 0 0 2.05-3.53ZM12 16.5h.01" />
        )}
      </svg>
    </span>
  );
}

export function ClientAlertsPanel() {
  const [data, setData] = useState<ClientAlerts | null>(null);

  useEffect(() => {
    let active = true;
    getBriefingClientAlerts()
      .then((result) => { if (active) setData(result); })
      .catch(() => { if (active) setData({ available: false, threshold_pct: 30, breaches: [] }); });
    return () => { active = false; };
  }, []);

  if (!data) {
    return (
      <section className="rounded-2xl border border-terminal-border bg-terminal-panel p-5 shadow-sm">
        <div className="animate-pulse">
          <div className="h-3 w-28 rounded bg-terminal-border/60" />
          <div className="mt-3 h-5 w-56 rounded bg-terminal-border/50" />
          <div className="mt-5 h-20 rounded-xl bg-terminal-border/30" />
        </div>
      </section>
    );
  }

  const hasBreaches = data.available && data.breaches.length > 0;

  return (
    <section className="rounded-2xl border border-terminal-border bg-terminal-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Portfolio risk</p>
          <h2 className="mt-1 text-xl font-semibold">Client concentration alerts</h2>
          <p className="mt-1 text-xs text-terminal-muted">Positions above the {data.threshold_pct}% concentration threshold.</p>
        </div>
        <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${
          hasBreaches
            ? "bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300"
            : "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300"
        }`}>
          {hasBreaches ? `${data.breaches.length} flagged` : data.available ? "All clear" : "Unavailable"}
        </span>
      </div>

      {hasBreaches ? (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          {data.breaches.map((breach) => (
            <article key={`${breach.label}:${breach.ticker}`} className="flex items-center gap-3 rounded-xl border border-amber-200/70 bg-amber-50/50 p-3.5 dark:border-amber-900/60 dark:bg-amber-950/20">
              <AlertIcon />
              <div className="min-w-0 flex-1">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-terminal-text">{breach.label}</p>
                    <p className="mt-0.5 text-xs text-terminal-muted">{breach.ticker} · {money.format(breach.market_value)}</p>
                  </div>
                  <span className="shrink-0 rounded-full bg-amber-100 px-2 py-1 text-xs font-bold tabular-nums text-amber-800 dark:bg-amber-900/60 dark:text-amber-200">
                    {breach.weight_pct.toFixed(1)}%
                  </span>
                </div>
              </div>
            </article>
          ))}
        </div>
      ) : (
        <div className="mt-4 flex items-center gap-3 rounded-xl border border-terminal-border bg-terminal-bg/40 p-4">
          <AlertIcon safe={data.available} />
          <div>
            <p className="text-sm font-semibold">{data.available ? "No concentration breaches" : "Concentration data unavailable"}</p>
            <p className="mt-0.5 text-xs text-terminal-muted">
              {data.available ? "Every monitored client is within the configured limit." : "The alert service could not be reached. Try again later."}
            </p>
          </div>
        </div>
      )}
    </section>
  );
}
