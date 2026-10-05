import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

// Same palette the other display components use (desk/displays/PortfolioPieChart.tsx).
const COLORS = ["#34d399", "#fbbf24", "#f87171", "#6b7a8d", "#1e3a5f", "#2563eb"];

export function SectorAllocationChart({ sectorAllocation }: { sectorAllocation: Record<string, number> | null }) {
  if (!sectorAllocation) return null;
  const data = Object.entries(sectorAllocation).map(([sector, weight_pct]) => ({ sector, weight_pct }));
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-2">
      <div className="h-40 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" stroke="#1c2733" />
            <XAxis type="number" tick={{ fill: "#6b7a8d", fontSize: 10 }} />
            <YAxis type="category" dataKey="sector" tick={false} width={4} />
            <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
            <Bar dataKey="weight_pct">
              {data.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {/* Plain HTML legend, not Recharts' SVG axis ticks: category tick
          labels rely on canvas text measurement, which jsdom doesn't
          implement, so they render empty in tests. This is also more
          precise for a reader than tiny rotated axis labels. */}
      <div className="mt-1 flex flex-col gap-1 px-2 pb-1 font-mono text-xs text-terminal-text">
        {data.map((d, i) => (
          <div key={d.sector} className="flex items-center justify-between gap-2">
            <span className="flex items-center gap-1.5">
              <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: COLORS[i % COLORS.length] }} />
              {d.sector}
            </span>
            <span className="text-terminal-muted">{d.weight_pct.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
