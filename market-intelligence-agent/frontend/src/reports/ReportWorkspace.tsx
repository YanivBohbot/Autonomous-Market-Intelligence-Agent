import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ConcentrationAlert } from "../desk/displays/ConcentrationAlert";
import { PortfolioPieChart } from "../desk/displays/PortfolioPieChart";
import { PortfolioTable } from "../desk/displays/PortfolioTable";
import { PriceChart } from "../desk/displays/PriceChart";
import { ReportFileCard } from "../desk/displays/ReportFileCard";
import { generateClientReport, getClientReport, getClientSummary, type ClientReport, type ClientSummary } from "../lib/api";
import { ErrorState, Skeleton } from "../ui/FeedbackStates";
import { MetricCard } from "../ui/MetricCard";
import { PageHeader } from "../ui/PageHeader";
import { SectionHeader } from "../ui/SectionHeader";
import { StatusBadge, type StatusTone } from "../ui/StatusBadge";
import { SurfaceCard } from "../ui/SurfaceCard";
import { SectorAllocationChart } from "./SectorAllocationChart";

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

function ReportWorkspaceLoading() {
  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1500px] space-y-4 p-4 sm:p-6 lg:p-8">
        <div className="rounded-3xl border border-terminal-border bg-terminal-panel p-5 shadow-sm md:p-6">
          <Skeleton className="h-28" label="Loading report profile" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28" label="Loading report metric" />)}
        </div>
      </div>
    </main>
  );
}

function SummaryMetrics({ summary }: { summary: ClientSummary }) {
  const pricedCount = summary.positions.length;
  const totalCount = pricedCount + summary.unpriced_tickers.length;
  const excluded = summary.unpriced_tickers.join(", ");

  if (!summary.totals) {
    const unavailable = summary.unpriced_tickers.length > 0;
    return (
      <section aria-label="Report summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Market value" value={unavailable ? "Prices unavailable" : "No positions"} detail={unavailable ? `${excluded} could not be priced` : "No holdings recorded"} tone={unavailable ? "warning" : "neutral"} />
        <MetricCard label="Unrealized P&L" value="—" detail="Awaiting priced positions" />
        <MetricCard label="Return" value="—" detail="Awaiting priced positions" />
        <MetricCard label="Price coverage" value={`${pricedCount} of ${totalCount}`} detail="Positions with current prices" tone={unavailable ? "warning" : "neutral"} />
      </section>
    );
  }

  const performanceTone: StatusTone = summary.totals.unrealized_pnl > 0
    ? "success"
    : summary.totals.unrealized_pnl < 0
      ? "danger"
      : "neutral";

  return (
    <section aria-label="Report summary" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <MetricCard label="Market value" value={currencyFormatter.format(summary.totals.market_value)} detail={excluded ? `Totals exclude ${excluded}` : "Current portfolio valuation"} tone="info" />
      <MetricCard label="Unrealized P&L" value={signedCurrency(summary.totals.unrealized_pnl)} detail={`Cost basis ${currencyFormatter.format(summary.totals.cost_basis)}`} tone={performanceTone} />
      <MetricCard label="Return" value={signedPercentage(summary.totals.unrealized_pnl_pct)} detail="Unrealized portfolio return" tone={performanceTone} />
      <MetricCard label="Price coverage" value={`${pricedCount} of ${totalCount}`} detail={excluded ? `${summary.unpriced_tickers.length} awaiting price` : "Full pricing coverage"} tone={excluded ? "warning" : "success"} />
    </section>
  );
}

function ReportWorkspaceBody({ clientId }: { clientId: number }) {
  const [summary, setSummary] = useState<ClientSummary | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [full, setFull] = useState<ClientReport | null>(null);
  const [fullLoading, setFullLoading] = useState(false);
  const [fullError, setFullError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setSummary(null);
    setSummaryError(null);
    setFull(null);
    setFullError(null);
    getClientSummary(clientId)
      .then((nextSummary) => {
        if (active) setSummary(nextSummary);
      })
      .catch(() => {
        if (active) setSummaryError("Failed to load this client.");
      });
    return () => {
      active = false;
    };
  }, [clientId]);

  function loadFull() {
    setFullLoading(true);
    setFullError(null);
    getClientReport(clientId)
      .then((report) => {
        setFull(report);
      })
      .catch(() => {
        setFullError("Failed to load the full report.");
      })
      .finally(() => {
        setFullLoading(false);
      });
  }

  async function onGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      await generateClientReport(clientId);
      loadFull();
    } catch (err) {
      setGenerateError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  if (summaryError) {
    return (
      <main className="min-h-0 flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-3xl space-y-4 p-4 sm:p-6 lg:p-8">
          <Link to="/reports" className="inline-flex rounded-xl border border-terminal-border px-3 py-2 text-sm font-semibold text-terminal-muted transition-colors hover:border-brand-blue/50 hover:text-brand-blue">
            Back to reports
          </Link>
          <ErrorState title="Failed to load client report" description={summaryError} />
        </div>
      </main>
    );
  }

  if (!summary) return <ReportWorkspaceLoading />;

  return (
    <main className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[1500px] space-y-6 p-4 sm:p-6 lg:p-8">
        <PageHeader
          eyebrow="Progressive portfolio report"
          title={summary.name}
          description={`${summary.email} · ${summary.city}`}
          actions={(
            <Link to="/reports" className="rounded-xl border border-terminal-border bg-terminal-panel px-3 py-2 text-sm font-semibold text-terminal-muted transition-colors hover:border-brand-blue/50 hover:text-brand-blue focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue">
              Back to reports
            </Link>
          )}
        >
          <div className="flex flex-wrap gap-2">
            <StatusBadge>{summary.segment}</StatusBadge>
            <StatusBadge tone={riskTone(summary.risk_profile)}>{titleCase(summary.risk_profile)} risk</StatusBadge>
            <StatusBadge>Advisor {summary.advisor}</StatusBadge>
          </div>
        </PageHeader>

        <SummaryMetrics summary={summary} />

        {!full && (
          <SurfaceCard tone="gradient" padding="lg" className="space-y-4">
            <SectionHeader
              title="Full portfolio report"
              description="Load narrative analysis, allocation charts, price trends, risk checks, positions, and generated files on demand."
              action={(
                <button type="button" onClick={loadFull} disabled={fullLoading} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50">
                  {fullLoading ? "Loading…" : "View full report"}
                </button>
              )}
            />
            {fullLoading && <Skeleton className="h-36" label="Loading full report" />}
            {fullError && <ErrorState title="Full report unavailable" description={fullError} actionLabel="Retry" onAction={loadFull} />}
          </SurfaceCard>
        )}

        {full && (
          <div className="space-y-6">
            <SurfaceCard padding="lg" className="space-y-4">
              <SectionHeader title="Analysis" description="Portfolio narrative generated from the latest available client data." />
              <div className="whitespace-pre-line text-sm leading-relaxed text-terminal-text">{full.narrative}</div>
            </SurfaceCard>

            <div className="grid gap-6 xl:grid-cols-2">
              {full.positions.length > 0 && (
                <SurfaceCard padding="lg" className="space-y-4">
                  <SectionHeader title="Portfolio allocation" description="Weight of each priced position." />
                  <PortfolioPieChart display={{ type: "portfolio_chart", slices: full.positions.map((position) => ({ ticker: position.ticker, weight_pct: position.weight_pct })) }} />
                </SurfaceCard>
              )}

              {full.sector_allocation && (
                <SurfaceCard padding="lg" className="space-y-4">
                  <SectionHeader title="Sector exposure" description="Portfolio value grouped by sector." />
                  <SectorAllocationChart sectorAllocation={full.sector_allocation} />
                </SurfaceCard>
              )}
            </div>

            {Object.keys(full.price_history).length > 0 && (
              <SurfaceCard padding="lg" className="space-y-4">
                <SectionHeader title="Price trends" description="Recent history for the largest portfolio positions." />
                <div className="grid gap-4 xl:grid-cols-2">
                  {Object.entries(full.price_history).map(([ticker, points]) => (
                    <PriceChart key={ticker} display={{ type: "price_chart", ticker, points }} />
                  ))}
                </div>
              </SurfaceCard>
            )}

            {full.concentration && full.concentration.breaches.length > 0 && (
              <SurfaceCard padding="lg" className="space-y-4">
                <SectionHeader title="Concentration risk" description={`Positions above the ${full.concentration.threshold_pct}% review threshold.`} />
                <ConcentrationAlert display={{ type: "concentration_alert", threshold_pct: full.concentration.threshold_pct, breaches: full.concentration.breaches }} />
              </SurfaceCard>
            )}

            <SurfaceCard padding="lg" className="space-y-4">
              <SectionHeader title="Positions" description="Current priced holdings and portfolio totals." />
              {full.totals ? (
                <PortfolioTable display={{ type: "portfolio_table", positions: full.positions, totals: full.totals }} />
              ) : full.unpriced_tickers.length > 0 ? (
                <ErrorState title="Prices unavailable" description={full.unpriced_tickers.join(", ")} />
              ) : (
                <p className="text-sm text-terminal-muted">No positions.</p>
              )}
            </SurfaceCard>

            <SurfaceCard padding="lg" className="space-y-4">
              <SectionHeader
                title="Generated reports"
                description="Download prior report files or generate a refreshed workbook."
                action={(
                  <button type="button" onClick={onGenerate} disabled={generating} className="rounded-xl bg-brand-blue px-4 py-2 text-sm font-semibold text-white transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50">
                    {generating ? "Generating…" : "Generate report"}
                  </button>
                )}
              />
              {generateError && <ErrorState title="Report generation failed" description={generateError} />}
              {full.generated_reports.length > 0 ? (
                <div className="grid gap-3 lg:grid-cols-2">
                  {full.generated_reports.map((file) => (
                    <ReportFileCard key={file.filename} display={{ type: "report_file", filename: file.filename, url: file.download_url }} />
                  ))}
                </div>
              ) : (
                <p className="text-sm text-terminal-muted">No generated reports yet.</p>
              )}
            </SurfaceCard>
          </div>
        )}
      </div>
    </main>
  );
}

export function ReportWorkspace() {
  const { id } = useParams<{ id: string }>();
  return <ReportWorkspaceBody key={id} clientId={Number(id)} />;
}
