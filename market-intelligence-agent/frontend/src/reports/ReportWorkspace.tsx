import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ConcentrationAlert } from "../desk/displays/ConcentrationAlert";
import { PortfolioPieChart } from "../desk/displays/PortfolioPieChart";
import { PortfolioTable } from "../desk/displays/PortfolioTable";
import { PriceChart } from "../desk/displays/PriceChart";
import { ReportFileCard } from "../desk/displays/ReportFileCard";
import { generateClientReport, getClientReport, type ClientReport } from "../lib/api";
import { SectorAllocationChart } from "./SectorAllocationChart";

function ReportWorkspaceBody({ clientId }: { clientId: number }) {
  const [report, setReport] = useState<ClientReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);

  function load() {
    getClientReport(clientId)
      .then(setReport)
      .catch(() => setError("Failed to load this client's report."));
  }

  useEffect(() => {
    let active = true;
    setReport(null);
    setError(null);
    getClientReport(clientId)
      .then((r) => {
        if (active) setReport(r);
      })
      .catch(() => {
        if (active) setError("Failed to load this client's report.");
      });
    return () => {
      active = false;
    };
  }, [clientId]);

  async function onGenerate() {
    setGenerating(true);
    setGenerateError(null);
    try {
      await generateClientReport(clientId);
      load();
    } catch (err) {
      setGenerateError((err as Error).message);
    } finally {
      setGenerating(false);
    }
  }

  if (error) {
    return (
      <main className="flex min-h-0 min-w-0 flex-1 flex-col items-center justify-center gap-3 font-mono text-sm">
        <div className="text-terminal-danger">{error}</div>
        <Link to="/reports" className="text-terminal-accent underline">
          Back to list
        </Link>
      </main>
    );
  }

  if (!report) return null;

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-auto p-4 font-mono text-sm text-terminal-text">
      <div>
        <Link to="/reports" className="mb-2 inline-block text-xs text-terminal-muted hover:text-terminal-accent">
          ← Back to list
        </Link>
        <div className="flex items-center justify-between">
          <div>
            <span className="font-semibold">{report.name}</span>
            <span className="ml-2 text-xs text-terminal-muted">
              {report.segment} · {report.risk_profile} · {report.advisor}
            </span>
          </div>
          {report.totals ? (
            <span className="text-xs text-terminal-accent">
              ${report.totals.market_value.toFixed(2)} ({report.totals.unrealized_pnl_pct.toFixed(1)}%)
              {report.unpriced_tickers.length > 0 && (
                <span className="ml-1 text-terminal-muted">(excl. {report.unpriced_tickers.join(", ")})</span>
              )}
            </span>
          ) : report.unpriced_tickers.length > 0 ? (
            <span className="text-xs text-terminal-danger">Prices unavailable</span>
          ) : (
            <span className="text-xs text-terminal-muted">No position.</span>
          )}
        </div>
      </div>

      {report.positions.length > 0 && (
        <PortfolioPieChart
          display={{ type: "portfolio_chart", slices: report.positions.map((p) => ({ ticker: p.ticker, weight_pct: p.weight_pct })) }}
        />
      )}

      <SectorAllocationChart sectorAllocation={report.sector_allocation} />

      {Object.entries(report.price_history).map(([ticker, points]) => (
        <PriceChart key={ticker} display={{ type: "price_chart", ticker, points }} />
      ))}

      {report.concentration && report.concentration.breaches.length > 0 && (
        <ConcentrationAlert
          display={{ type: "concentration_alert", threshold_pct: report.concentration.threshold_pct, breaches: report.concentration.breaches }}
        />
      )}

      {report.totals ? (
        <PortfolioTable display={{ type: "portfolio_table", positions: report.positions, totals: report.totals }} />
      ) : report.unpriced_tickers.length > 0 ? (
        <div className="text-xs text-terminal-danger">Prices unavailable ({report.unpriced_tickers.join(", ")})</div>
      ) : (
        <div className="text-xs text-terminal-muted">No position.</div>
      )}

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
        {report.generated_reports.map((f) => (
          <ReportFileCard key={f.filename} display={{ type: "report_file", filename: f.filename, url: f.download_url }} />
        ))}
      </div>
    </div>
  );
}

export function ReportWorkspace() {
  const { id } = useParams<{ id: string }>();
  return <ReportWorkspaceBody key={id} clientId={Number(id)} />;
}
