import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DisplayPayload } from "./types";

export function PriceChart({ display }: { display: Extract<DisplayPayload, { type: "price_chart" }> }) {
  return (
    <div className="w-full rounded-xl border border-terminal-border bg-terminal-panel p-3">
      <div className="mb-2 font-mono text-xs font-semibold text-terminal-text">{display.ticker || "Price history"}</div>
      <div className="h-48 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={display.points}>
            <XAxis dataKey="date" tick={{ fill: "#6b7a8d", fontSize: 10 }} />
            <YAxis domain={["auto", "auto"]} tick={{ fill: "#6b7a8d", fontSize: 10 }} width={50} />
            <Tooltip contentStyle={{ background: "#0f1620", border: "1px solid #1c2733", fontSize: 11 }} />
            <Line type="monotone" dataKey="close" stroke="#34d399" dot={false} strokeWidth={2} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
