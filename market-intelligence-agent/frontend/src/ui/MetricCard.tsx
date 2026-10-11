import type { ReactNode } from "react";
import type { StatusTone } from "./StatusBadge";

const VALUE_CLASSES: Record<StatusTone, string> = {
  neutral: "text-terminal-text",
  info: "text-blue-600 dark:text-blue-300",
  success: "text-emerald-600 dark:text-emerald-300",
  warning: "text-amber-600 dark:text-amber-300",
  danger: "text-terminal-danger",
};

export function MetricCard({ label, value, detail, tone = "neutral" }: { label: string; value: ReactNode; detail?: string; tone?: StatusTone }) {
  return (
    <article data-tone={tone} className="rounded-2xl border border-terminal-border bg-terminal-panel p-4 card-shadow">
      <p className="text-xs font-semibold uppercase tracking-[0.14em] text-terminal-muted">{label}</p>
      <div className={`mt-2 text-2xl font-semibold tracking-tight ${VALUE_CLASSES[tone]}`}>{value}</div>
      {detail && <p className="mt-1 text-xs text-terminal-muted">{detail}</p>}
    </article>
  );
}
