import type { ActivityItem } from "../lib/types";

// Node display config: color + short label
const NODE_CONFIG: Record<string, { color: string; label: string }> = {
  rag: { color: "text-sky-400", label: "RAG" },
  grader: { color: "text-violet-400", label: "GRADE" },
  web_search: { color: "text-amber-400", label: "SEARCH" },
  generate: { color: "text-terminal-accent", label: "GEN" },
  tools: { color: "text-pink-400", label: "TOOLS" },
  approval: { color: "text-terminal-warn", label: "GATE" },
};

function NodeBadge({ node }: { node: string }) {
  const cfg = NODE_CONFIG[node] ?? { color: "text-terminal-muted", label: node.toUpperCase().slice(0, 6) };
  return (
    <span
      className={`rounded px-1.5 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-wider ${cfg.color} bg-black/30`}
    >
      {cfg.label}
    </span>
  );
}

function ToolTag({ name }: { name: string }) {
  // Strip common yfinance_ prefix for brevity
  const display = name.replace(/^yfinance_/, "yf:");
  return (
    <span className="rounded border border-terminal-border bg-terminal-bg px-1 py-0.5 font-mono text-[9px] text-terminal-muted">
      {display}
    </span>
  );
}

function ActivityRow({ item }: { item: ActivityItem }) {
  const timeStr = new Date(item.ts).toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  return (
    <div className="animate-slide-in-right mb-2.5 border-l-2 border-terminal-border/50 pl-2.5 hover:border-terminal-accent/40 transition-colors">
      <div className="flex items-center justify-between gap-2">
        <NodeBadge node={item.node} />
        <span className="font-mono text-[9px] text-terminal-muted tabular-nums">{timeStr}</span>
      </div>
      {item.toolCalls && item.toolCalls.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {item.toolCalls.map((t) => (
            <ToolTag key={t} name={t} />
          ))}
        </div>
      )}
    </div>
  );
}

export function ActivityRail({ activity }: { activity: ActivityItem[] }) {
  return (
    <aside className="flex h-full w-64 flex-none flex-col border-l border-terminal-border bg-terminal-panel">
      {/* Rail header */}
      <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-terminal-muted">
          Agent activity
        </span>
        {activity.length > 0 && (
          <span className="rounded-full bg-terminal-accent/10 px-1.5 py-0.5 font-mono text-[9px] text-terminal-accent">
            {activity.length}
          </span>
        )}
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-y-auto p-3">
        {activity.length === 0 ? (
          <div className="flex flex-col items-center gap-2 pt-6 text-center">
            <div className="h-6 w-px bg-terminal-border" />
            <span className="font-mono text-[10px] text-terminal-muted">idle</span>
          </div>
        ) : (
          <div>
            {activity.map((a) => (
              <ActivityRow key={a.id} item={a} />
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
