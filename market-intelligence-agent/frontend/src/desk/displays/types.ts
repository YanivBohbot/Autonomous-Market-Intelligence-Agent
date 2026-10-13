// Wire contract with app/agent/display.py's DISPLAY_NORMALIZERS.
// Keys are snake_case, matching the Python source dicts 1:1 (no case-mapping
// layer), the same convention the backend API models use.

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

export interface ComparedCompany {
  symbol: string; name: string; sector: string | null; currency: string; price: number;
  market_cap: number | null; trailing_pe: number | null; forward_pe: number | null;
  range_position_pct: number | null; period_return_pct: number;
  points: { date: string; value: number }[];
}
export interface WhatIfSide {
  totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number };
  positions: { ticker: string; weight_pct: number; market_value: number }[];
}
export interface WatchlistRow {
  client: string; ticker: string; company: string; price: number; alert_price: number;
  direction: "above" | "below"; status: "triggered" | "near" | "watching"; distance_pct: number;
}

export type DisplayPayload =
  | { type: "portfolio_table"; positions: PortfolioPosition[]; totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number } }
  | { type: "portfolio_chart"; slices: { ticker: string; weight_pct: number }[] }
  | { type: "price_chart"; ticker: string; points: { date: string; close: number }[] }
  | { type: "ticker_info"; ticker: string; name: string; sector: string | null; industry: string | null; current_price: number; currency: string; market_cap: number | null; fifty_two_week_low: number | null; fifty_two_week_high: number | null }
  | { type: "ticker_news"; items: { title: string; summary: string; source: string; url: string; published_at: string }[] }
  | { type: "concentration_alert"; threshold_pct: number; breaches: { label: string; ticker: string; weight_pct: number; market_value: number }[] }
  | { type: "screenshot"; url: string }
  | { type: "rag_sources"; sources: { filename: string; page: string; excerpt: string }[] }
  | { type: "report_file"; filename: string; url: string }
  | { type: "file_list"; path: string; dirs: string[]; files: { name: string; url: string | null }[] }
  | { type: "company_comparison"; period: string; missing: string[]; companies: ComparedCompany[] }
  | { type: "what_if"; client_name: string; before: WhatIfSide; after: WhatIfSide; cash_delta: number; breaches_before: string[]; breaches_after: string[]; trades: { ticker: string; action: "buy" | "sell"; shares: number; price: number }[] }
  | { type: "watchlist_alerts"; near_pct: number; unpriced: string[]; rows: WatchlistRow[] }
  | { type: "sql_table"; columns: string[]; rows: unknown[][]; truncated: boolean };

export interface DisplayEnvelope {
  summary: string;
  displays: DisplayPayload[];
}
