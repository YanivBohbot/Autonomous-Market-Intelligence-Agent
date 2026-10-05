import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DisplayPayload } from "./types";

const _ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

// A full "2026-10-02" tick label on the rightmost point used to get
// clipped by the chart's edge -- Recharts' default 5px right margin isn't
// wide enough for a 10-character label anchored at the plot's last data
// point. Shortening to "10-02" fits comfortably without needing a much
// wider margin (which would shrink the plot area on narrow cards).
export function formatAxisDate(date: string): string {
  return _ISO_DATE.test(date) ? date.slice(5) : date;
}

export function PriceChart({ display }: { display: Extract<DisplayPayload, { type: "price_chart" }> }) {
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
      <div className="mb-2 font-mono text-xs font-semibold text-terminal-text">{display.ticker || "Price history"}</div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={display.points} margin={{ top: 5, right: 12, bottom: 5, left: 0 }}>
            <XAxis dataKey="date" tickFormatter={formatAxisDate} tick={{ fill: "#6b7a8d", fontSize: 10 }} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "#6b7a8d", fontSize: 10 }} width={50} />
            <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
            <Line type="monotone" dataKey="close" stroke="#34d399" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
