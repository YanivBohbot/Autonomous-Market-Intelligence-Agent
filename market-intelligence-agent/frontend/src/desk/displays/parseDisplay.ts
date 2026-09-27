import type { DisplayEnvelope, DisplayPayload } from "./types";

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// One predicate per type, checking only the fields the frontend actually
// reads — enough to catch a malformed/future entry without over-validating.
const VALIDATORS: Record<DisplayPayload["type"], (d: Record<string, unknown>) => boolean> = {
  portfolio_table: (d) => Array.isArray(d.positions) && isRecord(d.totals),
  portfolio_chart: (d) => Array.isArray(d.slices),
  price_chart: (d) => typeof d.ticker === "string" && Array.isArray(d.points),
  ticker_info: (d) => typeof d.name === "string" && typeof d.current_price === "number",
  ticker_news: (d) => Array.isArray(d.items),
  concentration_alert: (d) => Array.isArray(d.breaches),
  screenshot: (d) => typeof d.url === "string",
  rag_sources: (d) => Array.isArray(d.sources),
};

function isValidDisplay(entry: unknown): entry is DisplayPayload {
  if (!isRecord(entry) || typeof entry.type !== "string") return false;
  const validate = VALIDATORS[entry.type as DisplayPayload["type"]];
  return validate ? validate(entry) : false;
}

export function parseDisplay(raw: unknown): DisplayEnvelope | null {
  if (typeof raw !== "string") return null;
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data) || typeof data.summary !== "string" || !Array.isArray(data.displays)) return null;
  return { summary: data.summary, displays: data.displays.filter(isValidDisplay) };
}
