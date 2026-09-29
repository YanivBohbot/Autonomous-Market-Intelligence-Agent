import { z } from "zod";
import { useRenderTool } from "@copilotkit/react-core/v2";
import { parseDisplay } from "./parseDisplay";
import { PortfolioTable } from "./PortfolioTable";
import { PortfolioPieChart } from "./PortfolioPieChart";
import { PriceChart } from "./PriceChart";
import { TickerInfoCard } from "./TickerInfoCard";
import { TickerNewsList } from "./TickerNewsList";
import { ConcentrationAlert } from "./ConcentrationAlert";
import { ScreenshotCard } from "./ScreenshotCard";
import { RagSourceCards } from "./RagSourceCards";
import { ReportFileCard } from "./ReportFileCard";
import type { DisplayPayload } from "./types";

function Rendered({ displays, toolCallId }: { displays: DisplayPayload[]; toolCallId?: string }) {
  return (
    <div className="flex flex-col gap-2">
      {displays.map((d, i) => {
        switch (d.type) {
          case "portfolio_table": return <PortfolioTable key={i} display={d} />;
          case "portfolio_chart": return <PortfolioPieChart key={i} display={d} />;
          case "price_chart": return <PriceChart key={i} display={d} />;
          case "ticker_info": return <TickerInfoCard key={i} display={d} />;
          case "ticker_news": return <TickerNewsList key={i} display={d} />;
          case "concentration_alert": return <ConcentrationAlert key={i} display={d} />;
          case "screenshot": return <ScreenshotCard key={i} display={d} />;
          case "rag_sources": return <RagSourceCards key={i} display={d} toolCallId={toolCallId} />;
          case "report_file": return <ReportFileCard key={i} display={d} />;
        }
      })}
    </div>
  );
}

function renderDisplayResult(props: { status: string; result?: string; toolCallId?: string }) {
  // The activity rail already covers "still running"; nothing extra to show
  // here until the tool call actually has a result.
  if (props.status !== "complete") return null;
  const envelope = parseDisplay(props.result);
  if (!envelope || envelope.displays.length === 0) return null;
  return <Rendered displays={envelope.displays} toolCallId={props.toolCallId} />;
}

// Mirrors app/agent/multi_agent/display.py's DISPLAY_NORMALIZERS keys exactly.
const DISPLAYABLE_TOOLS = [
  "portfolio_metrics",
  "concentration_screen",
  "client_portfolio",
  "yfinance_get_price_history",
  "yfinance_get_ticker_info",
  "yfinance_get_ticker_news",
  "search_knowledge_base",
  "browser_take_screenshot",
  "write_file",
] as const;

// One named registration per tool — leaves every other tool call (read_query,
// save_memory, browser_navigate, browser_snapshot, send_email, ...) to
// CopilotKit's own default card, completely untouched. write_file is
// registered too, but its normalizer (display.py) only produces a display
// for a path under "reports/" -- a plain filesystem_agent write still falls
// through to the default card via the same "no displays" path every other
// unregistered tool uses.
export function useToolDisplay(): void {
  for (const name of DISPLAYABLE_TOOLS) {
    // eslint-disable-next-line react-hooks/rules-of-hooks -- DISPLAYABLE_TOOLS is a fixed compile-time list, never conditional or reordered across renders.
    useRenderTool({ name, parameters: z.any(), render: renderDisplayResult });
  }
}
