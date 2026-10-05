import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ConcentrationAlert } from "../desk/displays/ConcentrationAlert";
import { PortfolioPieChart } from "../desk/displays/PortfolioPieChart";
import { PortfolioTable } from "../desk/displays/PortfolioTable";
import { PriceChart } from "../desk/displays/PriceChart";
import { ReportFileCard } from "../desk/displays/ReportFileCard";
import { generateClientReport, getClientReport, getClientSummary, type ClientReport, type ClientSummary } from "../lib/api";
import { SectorAllocationChart } from "./SectorAllocationChart";

// Two-step on purpose (live QA feedback): a client row click used to go
// straight into the heavy dashboard (live prices + price history x3 +
// concentration + an LLM call), which showed nothing for several seconds.
// Step 1 reuses chantier 2's already-fast /summary endpoint so something
// useful appears immediately; step 2 (the full charts/narrative/concentration
// dashboard) only fetches once the user explicitly asks for it, with a
// visible loading state they're expecting.
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
      .then((s) => {
        if (active) setSummary(s);
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
      .then((r) => {
        setFull(r);
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
      <main className="flex min-h-0 min-w-0 flex-1 flex-col items-center justify-center gap-3 font-mono text-sm">
        <div className="text-terminal-danger">{summaryError}</div>
        <Link to="/reports" className="text-terminal-accent underline">
          Back to list
        </Link>
      </main>
    );
  }

  if (!summary) return null;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-auto p-4 font-mono text-sm text-terminal-text">
      <div>
        <Link to="/reports" className="mb-2 inline-block text-xs text-terminal-muted hover:text-terminal-accent">
          ← Back to list
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <span className="font-semibold">{summary.name}</span>
            <span className="ml-2 text-xs text-terminal-muted">
              {summary.segment} · {summary.risk_profile} · {summary.advisor}
            </span>
          </div>
          {summary.totals ? (
            <span className="text-xs text-terminal-accent">
              ${summary.totals.market_value.toFixed(2)} ({summary.totals.unrealized_pnl_pct.toFixed(1)}%)
              {summary.unpriced_tickers.length > 0 && (
                <span className="ml-1 text-terminal-muted">(excl. {summary.unpriced_tickers.join(", ")})</span>
              )}
            </span>
          ) : summary.unpriced_tickers.length > 0 ? (
            <span className="text-xs text-terminal-danger">Prices unavailable</span>
          ) : (
            <span className="text-xs text-terminal-muted">No position.</span>
          )}
        </div>
      </div>

      {!full && (
        <div className="flex flex-col items-start gap-2">
          <button
            type="button"
            onClick={loadFull}
            disabled={fullLoading}
            className="rounded-xl bg-terminal-accent px-4 py-2 font-mono text-sm font-semibold text-terminal-bg transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {fullLoading ? "Loading…" : "View full report"}
          </button>
          {fullError && <div className="text-xs text-terminal-danger">{fullError}</div>}
        </div>
      )}

      {full && (
        <>
          <section className="flex flex-col gap-1.5">
            <h3 className="text-xs font-semibold text-terminal-muted">Analysis</h3>
            <div className="whitespace-pre-line rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 text-xs leading-relaxed text-terminal-text">
              {full.narrative}
            </div>
          </section>

          {full.positions.length > 0 && (
            <section className="flex flex-col gap-1.5">
              <h3 className="text-xs font-semibold text-terminal-muted">Portfolio allocation</h3>
              <PortfolioPieChart
                display={{ type: "portfolio_chart", slices: full.positions.map((p) => ({ ticker: p.ticker, weight_pct: p.weight_pct })) }}
              />
            </section>
          )}

          {full.sector_allocation && (
            <section className="flex flex-col gap-1.5">
              <h3 className="text-xs font-semibold text-terminal-muted">Sector exposure</h3>
              <SectorAllocationChart sectorAllocation={full.sector_allocation} />
            </section>
          )}

          {Object.keys(full.price_history).length > 0 && (
            <section className="flex flex-col gap-1.5">
              <h3 className="text-xs font-semibold text-terminal-muted">Price trend (largest positions)</h3>
              {Object.entries(full.price_history).map(([ticker, points]) => (
                <PriceChart key={ticker} display={{ type: "price_chart", ticker, points }} />
              ))}
            </section>
          )}

          {full.concentration && full.concentration.breaches.length > 0 && (
            <section className="flex flex-col gap-1.5">
              <h3 className="text-xs font-semibold text-terminal-muted">Concentration risk</h3>
              <ConcentrationAlert
                display={{ type: "concentration_alert", threshold_pct: full.concentration.threshold_pct, breaches: full.concentration.breaches }}
              />
            </section>
          )}

          <section className="flex flex-col gap-1.5">
            <h3 className="text-xs font-semibold text-terminal-muted">Positions</h3>
            {full.totals ? (
              <PortfolioTable display={{ type: "portfolio_table", positions: full.positions, totals: full.totals }} />
            ) : full.unpriced_tickers.length > 0 ? (
              <div className="text-xs text-terminal-danger">Prices unavailable ({full.unpriced_tickers.join(", ")})</div>
            ) : (
              <div className="text-xs text-terminal-muted">No position.</div>
            )}
          </section>

          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs text-terminal-muted">Generated reports</span>
              <button
                type="button"
                onClick={onGenerate}
                disabled={generating}
                className="rounded-xl bg-terminal-accent px-3 py-1.5 font-mono text-xs font-semibold text-terminal-bg transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {generating ? "Generating…" : "Generate report"}
              </button>
            </div>
            {generateError && <div className="text-xs text-terminal-danger">{generateError}</div>}
            {full.generated_reports.map((f) => (
              <ReportFileCard key={f.filename} display={{ type: "report_file", filename: f.filename, url: f.download_url }} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

export function ReportWorkspace() {
  const { id } = useParams<{ id: string }>();
  return <ReportWorkspaceBody key={id} clientId={Number(id)} />;
}
