import { Line, LineChart, ResponsiveContainer } from "recharts";

export function Sparkline({ points, color = "#34d399" }: { points: { date: string; close: number }[]; color?: string })
 {
  if (points.length === 0) return null;
  return (
    <div className="h-10 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <Line type="monotone" dataKey="close" stroke={color} dot={false} strokeWidth={1.8} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
