import { useEffect, useState } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "./constants";
import { reduceActivity, type AgUiEvent, type DeskActivity } from "./activity";

const LABEL_COLOR: Record<string, string> = {
  RAG: "text-sky-400",
  FINANCE: "text-amber-400",
  PORTFOLIO: "text-terminal-accent",
  BROWSER: "text-violet-400",
  EMAIL: "text-pink-400",
  FILES: "text-teal-400",
  MEMORY: "text-indigo-400",
};

function time(ts: number) {
  return new Date(ts).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

function Row({ item }: { item: DeskActivity }) {
  let body;
  switch (item.kind) {
    case "specialist":
      body = (
        <span className={`rounded bg-black/30 px-1.5 py-0.5 font-mono text-[10px] font-semibold tracking-wider ${LABEL_COLOR[item.label]}`}>
          {item.label}
        </span>
      );
      break;
    case "tool":
      body = (
        <span className="rounded border border-terminal-border bg-terminal-bg px-1 py-0.5 font-mono text-[9px] text-terminal-muted">
          {item.name.replace(/^yfinance_/, "yf:")}
          {item.status === "running" ? " …" : item.durationMs !== undefined ? ` · ${item.durationMs} ms` : ""}
        </span>
      );
      break;
    case "awaiting":
      body = <span className="font-mono text-[10px] text-terminal-warn">awaiting approval</span>;
      break;
    case "done":
      body = (
        <span className="font-mono text-[10px] text-terminal-accent">
          done{item.totalTokens !== null ? ` · ${item.totalTokens} tokens` : ""}
        </span>
      );
      break;
    case "error":
      body = <span className="font-mono text-[10px] text-terminal-danger">error · {item.message}</span>;
      break;
  }
  return (
    <div className="animate-slide-in-right mb-2.5 flex items-center justify-between gap-2 border-l-2 border-terminal-border/50 pl-2.5">
      {body}
      <span className="font-mono text-[9px] tabular-nums text-terminal-muted">{time(item.ts)}</span>
    </div>
  );
}

// Same agent instance CopilotChat drives (useAgent({agentId}) without a
// threadId; a threadId would create a private, thread-scoped copy). DeskView is
// remounted per thread, so the list never mixes sessions.
export function DeskActivityRail() {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const [items, setItems] = useState<DeskActivity[]>([]);

  useEffect(() => {
    const sub = agent.subscribe({
      onEvent: ({ event }) => {
        setItems((prev) => reduceActivity(prev, event as unknown as AgUiEvent, Date.now()));
      },
      // HTTP errors (404 flag off, 503 starting) and dropped streams never
      // arrive as a RUN_ERROR event.
      onRunFailed: ({ error }) => {
        const failure: AgUiEvent = { type: "RUN_ERROR", message: error?.message ?? String(error) };
        setItems((prev) => reduceActivity(prev, failure, Date.now()));
      },
    });
    return () => sub.unsubscribe();
  }, [agent]);

  return (
    <aside className="flex h-full w-64 flex-none flex-col border-l border-terminal-border bg-terminal-panel">
      <div className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-widest text-terminal-muted">Agent activity</span>
      </div>
      <div className="flex-1 overflow-y-auto p-3">
        {items.length === 0 ? (
          <div className="pt-6 text-center font-mono text-[10px] text-terminal-muted">idle</div>
        ) : (
          items.map((it) => <Row key={it.id} item={it} />)
        )}
      </div>
    </aside>
  );
}
