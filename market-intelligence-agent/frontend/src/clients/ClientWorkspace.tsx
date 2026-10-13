import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { DeskView } from "../desk/DeskView";
import { CLIENT_STARTERS } from "../desk/starters";
import { HoldingsStrip } from "./HoldingsStrip";
import { getClientSummary, type ClientSummary } from "../lib/api";
import { ErrorState, Skeleton } from "../ui/FeedbackStates";
import { MetricCard } from "../ui/MetricCard";
import { PageHeader } from "../ui/PageHeader";
import { StatusBadge, type StatusTone } from "../ui/StatusBadge";

const currencyFormatter = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function titleCase(value: string) {
  return value ? `${value[0].toUpperCase()}${value.slice(1)}` : "Unknown";
}

function riskTone(profile: string): StatusTone {
  const normalized = profile.toLowerCase();
  if (normalized.includes("aggressive") || normalized.includes("high")) return "warning";
  if (normalized.includes("conservative") || normalized.includes("low")) return "success";
  return "info";
}

function signedCurrency(value: number) {
  if (value === 0) return currencyFormatter.format(value);
  return `${value > 0 ? "+" : "-"}${currencyFormatter.format(Math.abs(value))}`;
}

function signedPercentage(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(1)}%`;
}

function ClientWorkspaceLoading() {
  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1500px] space-y-4 p-4 sm:p-6 lg:p-8">
        <div className="rounded-3xl border border-terminal-border bg-terminal-panel p-5 shadow-sm md:p-6">
          <Skeleton className="h-28" label="Loading client profile" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => (
            <Skeleton key={index} className="h-28" label="Loading client metric" />
          ))}
        </div>
      </div>
    </main>
  );
}

function PortfolioMetrics({ summary }: { summary: ClientSummary }) {
  const pricedCount = summary.positions.length;
  const totalCount = pricedCount + summary.unpriced_tickers.length;
  const excluded = summary.unpriced_tickers.join(", ");
  const partialPricingDetail = excluded ? `Totals exclude ${excluded}` : "Current portfolio valuation";

  if (!summary.totals) {
    const unavailable = summary.unpriced_tickers.length > 0;
    return (
      <section aria-label="Portfolio overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          label="Market value"
          value={unavailable ? "Pricing unavailable" : "No positions"}
          detail={unavailable ? `${excluded} could not be priced` : "No holdings recorded"}
          tone={unavailable ? "warning" : "neutral"}
        />
        <MetricCard label="Unrealized P&L" value="—" detail="Awaiting priced positions" />
        <MetricCard label="Return" value="—" detail="Awaiting priced positions" />
        <MetricCard label="Priced positions" value={`${pricedCount} of ${totalCount}`} detail={unavailable ? "Pricing coverage" : "No holdings recorded"} />
      </section>
    );
  }

  const pnlTone: StatusTone = summary.totals.unrealized_pnl > 0
    ? "success"
    : summary.totals.unrealized_pnl < 0
      ? "danger"
      : "neutral";

  return (
    <section aria-label="Portfolio overview" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Market value" value={currencyFormatter.format(summary.totals.market_value)} detail={partialPricingDetail} tone="info" />
      <MetricCard label="Unrealized P&L" value={signedCurrency(summary.totals.unrealized_pnl)} detail={`Cost basis ${currencyFormatter.format(summary.totals.cost_basis)}`} tone={pnlTone} />
      <MetricCard label="Return" value={signedPercentage(summary.totals.unrealized_pnl_pct)} detail="Unrealized portfolio return" tone={pnlTone} />
      <MetricCard label="Priced positions" value={`${pricedCount} of ${totalCount}`} detail={excluded ? `${summary.unpriced_tickers.length} awaiting price` : "Full pricing coverage"} tone={excluded ? "warning" : "success"} />
    </section>
  );
}

function ClientWorkspaceBody({ clientId }: { clientId: number }) {
  const [summary, setSummary] = useState<ClientSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [retryVersion, setRetryVersion] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setSummary(null);
    setError(null);
    getClientSummary(clientId)
      .then((nextSummary) => {
        if (active) setSummary(nextSummary);
      })
      .catch(() => {
        if (active) setError("The latest client summary could not be loaded. Check the API connection and try again.");
      });
    return () => {
      active = false;
    };
  }, [clientId, retryVersion]);

  if (error) {
    return (
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-4 p-4 sm:p-6 lg:p-8">
          <Link to="/clients" className="inline-flex rounded-xl border border-terminal-border px-3 py-2 text-sm font-semibold text-terminal-muted transition-colors hover:border-brand-blue/50 hover:text-brand-blue">
            Back to clients
          </Link>
          <ErrorState
            title="Client workspace unavailable"
            description={error}
            actionLabel="Retry"
            onAction={() => setRetryVersion((version) => version + 1)}
          />
        </div>
      </main>
    );
  }

  if (!summary) return <ClientWorkspaceLoading />;

  const selectedPosition = summary.positions.find((p) => p.ticker === selected);
  const agentContext = [
    {
      description: "Client workspace on screen",
      value: JSON.stringify({ client: summary.name, totals: summary.totals, priced_positions: summary.positions.length }),
    },
    ...(selectedPosition ? [{ description: "Selected position", value: JSON.stringify({ client: summary.name, ...selectedPosition }) }] : []),
  ];

  return (
    // The page scrolls and the chat keeps a usable height: on a laptop screen
    // the client header + metrics + holdings left the chat ~100px tall.
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto">
      <div className="shrink-0 border-b border-terminal-border bg-terminal-bg/65">
        <div className="mx-auto w-full max-w-[1500px] space-y-4 p-4 sm:p-6 lg:px-8 lg:py-6">
          <PageHeader
            eyebrow="Client workspace"
            title={summary.name}
            description={`${summary.email} · ${summary.city}`}
            actions={(
              <Link to="/clients" className="rounded-xl border border-terminal-border bg-terminal-panel px-3 py-2 text-sm font-semibold text-terminal-muted transition-colors hover:border-brand-blue/50 hover:text-brand-blue focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue">
                Back to clients
              </Link>
            )}
          >
            <div className="flex flex-wrap gap-2">
              <StatusBadge tone="info">{summary.segment}</StatusBadge>
              <StatusBadge tone={riskTone(summary.risk_profile)}>{titleCase(summary.risk_profile)} risk</StatusBadge>
              <StatusBadge>Advisor {summary.advisor}</StatusBadge>
            </div>
          </PageHeader>
          <PortfolioMetrics summary={summary} />
          <HoldingsStrip positions={summary.positions} selected={selected} onSelect={setSelected} />
        </div>
      </div>
      <div className="flex min-h-[560px] flex-1">
        <DeskView threadId={`clients_${clientId}`} voiceEnabled={false} starterSuggestions={CLIENT_STARTERS} agentContext={agentContext} />
      </div>
    </div>
  );
}

export function ClientWorkspace() {
  const { id } = useParams<{ id: string }>();
  // A route-param change does not remount a component by default. This key
  // keeps each client's summary and Desk activity strictly isolated.
  return <ClientWorkspaceBody key={id} clientId={Number(id)} />;
}
