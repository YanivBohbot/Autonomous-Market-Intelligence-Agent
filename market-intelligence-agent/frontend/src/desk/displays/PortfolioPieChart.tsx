import { Cell, Legend, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import type { DisplayPayload } from "./types";

// Terminal palette, cycled per slice — no new colors introduced.
const COLORS = ["#34d399", "#fbbf24", "#f87171", "#6b7a8d", "#1e3a5f", "#2563eb"];

export function PortfolioPieChart({ display }: { display: Extract<DisplayPayload, { type: "portfolio_chart" }> }) {
  const data = display.slices.map((s) => ({ name: s.ticker, value: s.weight_pct }));
  return (
    <div className="h-56 w-full rounded-xl border border-terminal-border bg-terminal-panel p-2">
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie data={data} dataKey="value" nameKey="name" innerRadius={40} outerRadius={70}>
            {data.map((_, i) => (
              <Cell key={i} fill={COLORS[i % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
          <Legend wrapperStyle={{ fontSize: 11 }} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
}
