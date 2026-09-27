// Wire contract with app/agent/multi_agent/display.py's DISPLAY_NORMALIZERS.
// Keys are snake_case, matching the Python source dicts 1:1 (no case-mapping
// layer), the same convention this codebase's ApproveResponse already uses.

export interface PortfolioPosition {
  ticker: string;
  shares: number;
  price: number;
  market_value: number;
  cost_basis: number;
  unrealized_pnl: number;
  unrealized_pnl_pct: number;
  weight_pct: number;
  sector: string | null;
}

export type DisplayPayload =
  | { type: "portfolio_table"; positions: PortfolioPosition[]; totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number } }
  | { type: "portfolio_chart"; slices: { ticker: string; weight_pct: number }[] }
  | { type: "price_chart"; ticker: string; points: { date: string; close: number }[] }
  | { type: "ticker_info"; ticker: string; name: string; sector: string | null; industry: string | null; current_price: number; currency: string; market_cap: number | null; fifty_two_week_low: number | null; fifty_two_week_high: number | null }
  | { type: "ticker_news"; items: { title: string; summary: string; source: string; url: string; published_at: string }[] }
  | { type: "concentration_alert"; threshold_pct: number; breaches: { label: string; ticker: string; weight_pct: number; market_value: number }[] }
  | { type: "screenshot"; url: string }
  | { type: "rag_sources"; sources: { filename: string; page: string; excerpt: string }[] };

export interface DisplayEnvelope {
  summary: string;
  displays: DisplayPayload[];
}
