import { useEffect, useState } from "react";
import { getBriefingClientAlerts, type BriefingData } from "../lib/api";
import { Skeleton } from "../ui/FeedbackStates";
import { SectionHeader } from "../ui/SectionHeader";
import { StatusBadge, type StatusTone } from "../ui/StatusBadge";
import { SurfaceCard } from "../ui/SurfaceCard";

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
      <SurfaceCard padding="lg">
        <div className="space-y-3">
          <Skeleton className="h-3 w-28" label="Loading concentration alert category" />
          <Skeleton className="h-5 w-56" label="Loading concentration alert heading" />
          <Skeleton className="mt-2 h-20" label="Loading concentration alert details" />
        </div>
      </SurfaceCard>
    );
  }

  const hasBreaches = data.available && data.breaches.length > 0;
  const statusTone: StatusTone = hasBreaches ? "warning" : data.available ? "success" : "neutral";

  return (
    <SurfaceCard padding="lg">
      <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600 dark:text-blue-300">Portfolio risk</p>
      <div className="mt-1">
        <SectionHeader
          title="Client concentration alerts"
          description={`Positions above the ${data.threshold_pct}% concentration threshold.`}
          action={(
            <StatusBadge tone={statusTone}>
              {hasBreaches ? `${data.breaches.length} flagged` : data.available ? "All clear" : "Unavailable"}
            </StatusBadge>
          )}
        />
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
                  <StatusBadge tone="warning">
                    {breach.weight_pct.toFixed(1)}%
                  </StatusBadge>
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
    </SurfaceCard>
  );
}
