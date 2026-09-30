import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Capture every useRenderTool registration instead of a real CopilotKit
// provider — mirrors sub-project 1's DeskActivityRail.test.tsx pattern of
// mocking the SDK boundary and driving it directly.
const registrations: Record<string, (props: { status: string; result?: string }) => unknown> = {};
vi.mock("@copilotkit/react-core/v2", () => ({
  useRenderTool: (config: { name: string; render: (props: { status: string; result?: string }) => unknown }) => {
    registrations[config.name] = config.render;
  },
}));

import { useToolDisplay } from "./useToolDisplay";

function Harness() {
  useToolDisplay();
  return null;
}

describe("useToolDisplay", () => {
  it("registers a renderer for all 9 displayable tools", () => {
    render(<Harness />);
    expect(Object.keys(registrations).sort()).toEqual([
      "browser_take_screenshot", "client_portfolio", "concentration_screen", "portfolio_metrics",
      "save_portfolio_report", "search_knowledge_base", "yfinance_get_price_history",
      "yfinance_get_ticker_info", "yfinance_get_ticker_news",
    ]);
  });

  it("renders nothing while the tool call is still executing", () => {
    render(<Harness />);
    const result = registrations["portfolio_metrics"]({ status: "executing" });
    expect(result).toBeNull();
  });

  it("renders the matching component once the tool call completes", () => {
    render(<Harness />);
    const envelope = JSON.stringify({
      summary: "text",
      displays: [{ type: "portfolio_table", positions: [], totals: { market_value: 0, cost_basis: 0, unrealized_pnl: 0, unrealized_pnl_pct: 0 } }],
    });
    const { container } = render(<>{registrations["portfolio_metrics"]({ status: "complete", result: envelope })}</>);
    expect(container.querySelector("table")).toBeInTheDocument();
  });

  it("renders nothing when the result doesn't parse as a display envelope", () => {
    render(<Harness />);
    const result = registrations["portfolio_metrics"]({ status: "complete", result: "plain text answer" });
    expect(result).toBeNull();
  });

  it("renders a download card for a report_file display", () => {
    render(<Harness />);
    const envelope = JSON.stringify({
      summary: "Report saved.",
      displays: [{ type: "report_file", filename: "brief.xlsx", url: "/workspace/files/brief.xlsx" }],
    });
    render(<>{registrations["save_portfolio_report"]({ status: "complete", result: envelope })}</>);
    expect(screen.getByText("brief.xlsx")).toBeInTheDocument();
  });
});
