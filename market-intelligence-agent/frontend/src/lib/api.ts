import type { ApproveResponse, HealthResponse } from "./types";

// In dev, Vite proxies these paths to the backend, so "" (same origin) works.
export const API_BASE = "";

export async function getHealth(base = API_BASE): Promise<HealthResponse> {
  const res = await fetch(`${base}/health`);
  if (!res.ok) throw new Error(`health ${res.status}`);
  return res.json();
}

export async function postApprove(
  threadId: string,
  approved: boolean,
  base = API_BASE,
): Promise<ApproveResponse> {
  const res = await fetch(`${base}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, approved }),
  });
  if (!res.ok) throw new Error(`approve ${res.status}: ${await res.text()}`);
  return res.json();
}

export function newThreadId(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `web_session_${rand}`;
}

export async function uploadToWorkspace(file: File, base = API_BASE): Promise<{ path: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${base}/copilot/uploads`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`upload ${res.status}: ${await res.text()}`);
  return res.json();
}

export interface ClientWithHoldings {
  client_id: number;
  name: string;
  email: string;
  segment: string;
  risk_profile: string;
  advisor: string;
  city: string;
  holdings: { ticker: string; shares: number; avg_cost: number }[];
}

export interface ClientSummary {
  client_id: number;
  name: string;
  email: string;
  segment: string;
  risk_profile: string;
  advisor: string;
  city: string;
  totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number } | null;
  positions: {
    ticker: string; shares: number; avg_cost: number; price: number;
    market_value: number; cost_basis: number; unrealized_pnl: number;
    unrealized_pnl_pct: number; weight_pct: number; sector: string | null;
  }[];
  unpriced_tickers: string[];
}

export async function getClientSummary(clientId: number, base = API_BASE): Promise<ClientSummary> {
  const res = await fetch(`${base}/data/clients/${clientId}/summary`);
  if (!res.ok) throw new Error(`client summary ${res.status}`);
  return res.json();
}

export interface GeneratedReportFile {
  filename: string;
  generated_at: string;
  download_url: string;
}

export interface ClientReport {
  client_id: number;
  name: string;
  email: string;
  segment: string;
  risk_profile: string;
  advisor: string;
  city: string;
  totals: { market_value: number; cost_basis: number; unrealized_pnl: number; unrealized_pnl_pct: number } | null;
  positions: {
    ticker: string; shares: number; price: number; sector: string | null;
    market_value: number; cost_basis: number; unrealized_pnl: number;
    unrealized_pnl_pct: number; weight_pct: number;
  }[];
  sector_allocation: Record<string, number> | null;
  concentration: { threshold_pct: number; breach_count: number; breaches: { label: string; ticker: string; weight_pct: number; market_value: number }[] } | null;
  price_history: Record<string, { date: string; close: number }[]>;
  unpriced_tickers: string[];
  generated_reports: GeneratedReportFile[];
  narrative: string;
}

export async function getClientReport(clientId: number, base = API_BASE): Promise<ClientReport> {
  const res = await fetch(`${base}/data/clients/${clientId}/report`);
  if (!res.ok) throw new Error(`client report ${res.status}`);
  return res.json();
}

async function _detailOrStatus(res: Response, fallbackLabel: string): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // body wasn't JSON -- fall through to the generic message
  }
  return `${fallbackLabel} ${res.status}`;
}

export async function generateClientReport(clientId: number, base = API_BASE): Promise<{ filename: string }> {
  const res = await fetch(`${base}/data/clients/${clientId}/report/generate`, { method: "POST" });
  if (!res.ok) throw new Error(await _detailOrStatus(res, "generate report"));
  return res.json();
}

export interface ThreadMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

export async function getThreadHistory(threadId: string, base = API_BASE): Promise<ThreadMessage[]> {
  const res = await fetch(`${base}/copilot/market-desk/history?thread_id=${threadId}`);
  if (!res.ok) throw new Error(`thread history ${res.status}`);
  return res.json();
}

export interface ImportPreviewResult {
  type: "clients" | "holdings";
  valid: boolean;
  rows: Record<string, unknown>[];
  errors: { row: number; field: string; message: string }[];
}

export async function getClients(base = API_BASE): Promise<ClientWithHoldings[]> {
  const res = await fetch(`${base}/data/clients`);
  if (!res.ok) throw new Error(`clients ${res.status}`);
  return res.json();
}

export async function getDocuments(base = API_BASE): Promise<string[]> {
  const res = await fetch(`${base}/data/documents`);
  if (!res.ok) throw new Error(`documents ${res.status}`);
  return res.json();
}

export async function importPdf(file: File, base = API_BASE): Promise<{ filename: string; chunks_added: number }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${base}/data/import/pdf`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`import pdf ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function previewImport(rows: Record<string, unknown>[], base = API_BASE): Promise<ImportPreviewResult> {
  const res = await fetch(`${base}/data/import/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rows }),
  });
  if (res.status === 400) throw new Error("unrecognized file format");
  if (!res.ok) throw new Error(`preview ${res.status}`);
  return res.json();
}

export async function confirmImport(
  type: "clients" | "holdings",
  rows: Record<string, unknown>[],
  base = API_BASE,
): Promise<{ written: number }> {
  const res = await fetch(`${base}/data/import/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, rows }),
  });
  if (!res.ok) throw new Error(`confirm ${res.status}: ${await res.text()}`);
  return res.json();
}
