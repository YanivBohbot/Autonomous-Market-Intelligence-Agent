import type { ActivityItem } from "../lib/types";

const nodeColor: Record<string, string> = {
  rag: "text-sky-400",
  grader: "text-violet-400",
  web_search: "text-amber-400",
  generate: "text-terminal-accent",
  tools: "text-pink-400",
};

export function ActivityRail({ activity }: { activity: ActivityItem[] }) {
  return (
    <aside className="flex h-full w-72 flex-col border-l border-terminal-border bg-terminal-panel">
      <div className="border-b border-terminal-border px-3 py-2 font-mono text-xs uppercase tracking-wider text-terminal-muted">
        Agent activity
      </div>
      <div className="flex-1 overflow-y-auto p-3 font-mono text-xs">
        {activity.length === 0 && <p className="text-terminal-muted">idle</p>}
        {activity.map((a) => (
          <div key={a.id} className="mb-2 border-l-2 border-terminal-border pl-2">
            <span className={nodeColor[a.node] ?? "text-terminal-text"}>{a.node}</span>
            {a.toolCalls && a.toolCalls.length > 0 && (
              <div className="mt-0.5 text-terminal-muted">→ {a.toolCalls.join(", ")}</div>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
