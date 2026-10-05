import { Line, LineChart, ResponsiveContainer } from "recharts";

export function Sparkline({ points }: { points: { date: string; close: number }[] }) {
  if (points.length === 0) return null;
  return (
    <div className="h-10 w-full">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={points}>
          <Line type="monotone" dataKey="close" stroke="#34d399" dot={false} strokeWidth={1.5} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
