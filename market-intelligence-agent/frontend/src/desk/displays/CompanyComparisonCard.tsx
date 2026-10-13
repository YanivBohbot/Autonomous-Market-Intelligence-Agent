import { Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatAxisDate } from "./PriceChart";
import type { ComparedCompany, DisplayPayload } from "./types";

const COLORS = ["#34d399", "#60a5fa", "#fbbf24", "#f87171"];

export function mergeSeries(companies: ComparedCompany[]): Record<string, string | number>[] {
  const byDate = new Map<string, Record<string, string | number>>();
  for (const c of companies) {
    for (const p of c.points) {
      const row = byDate.get(p.date) ?? { date: p.date };
      row[c.symbol] = p.value;
      byDate.set(p.date, row);
    }
  }
  return [...byDate.values()].sort((a, b) => String(a.date).localeCompare(String(b.date)));
}

function money(v: number | null): string {
  if (v === null) return "—";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  return `$${v.toLocaleString("en-US")}`;
}
const num = (v: number | null) => (v === null ? "—" : v.toFixed(1));
const signed = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(1)}%`;

export function CompanyComparisonCard({ display }: { display: Extract<DisplayPayload, { type: "company_comparison" }> }) {
  const rows: [string, (c: ComparedCompany) => string][] = [
    ["Price", (c) => `${c.price.toFixed(2)} ${c.currency}`],
    ["Market cap", (c) => money(c.market_cap)],
    ["P/E (trailing)", (c) => num(c.trailing_pe)],
    ["P/E (forward)", (c) => num(c.forward_pe)],
    ["52-week range", (c) => (c.range_position_pct === null ? "—" : `${c.range_position_pct.toFixed(0)}% of range`)],
    [`Return (${display.period})`, (c) => signed(c.period_return_pct)],
  ];
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
      <div className="mb-2 font-semibold">Comparison · {display.period}</div>
      <table className="w-full">
        <thead>
          <tr>
            <th className="text-left font-normal text-terminal-muted" />
            {display.companies.map((c, i) => (
              <th key={c.symbol} className="text-right" style={{ color: COLORS[i % COLORS.length] }}>{c.symbol}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, cell]) => (
            <tr key={label}>
              <td className="py-0.5 text-terminal-muted">{label}</td>
              {display.companies.map((c) => <td key={c.symbol} className="py-0.5 text-right">{cell(c)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-3 h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={mergeSeries(display.companies)} margin={{ top: 5, right: 12, bottom: 5, left: 0 }}>
            <XAxis dataKey="date" tickFormatter={formatAxisDate} tick={{ fill: "#6b7a8d", fontSize: 10 }} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "#6b7a8d", fontSize: 10 }} width={40} />
            <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
            <Legend wrapperStyle={{ fontSize: 10 }} />
            {display.companies.map((c, i) => (
              <Line key={c.symbol} type="monotone" dataKey={c.symbol} stroke={COLORS[i % COLORS.length]} dot={false} strokeWidth={2} connectNulls />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="mt-1 text-[10px] text-terminal-muted">Prices rebased to 100 at the start of the period.</div>
      {display.missing.length > 0 && <div className="mt-1 text-terminal-warn">No data for {display.missing.join(", ")}</div>}
    </div>
  );
}
