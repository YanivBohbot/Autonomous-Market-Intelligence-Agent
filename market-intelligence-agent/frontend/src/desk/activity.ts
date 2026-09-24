// Pure AG-UI event → activity-row reducer for the Market Desk rail.

export type SpecialistLabel = "RAG" | "FINANCE" | "PORTFOLIO" | "BROWSER" | "EMAIL" | "FILES" | "MEMORY";

export type DeskActivity =
  | { kind: "specialist"; id: string; ts: number; label: SpecialistLabel }
  | { kind: "tool"; id: string; ts: number; toolCallId: string; name: string; status: "running" | "done"; durationMs?: number }
  | { kind: "awaiting"; id: string; ts: number }
  | { kind: "done"; id: string; ts: number; totalTokens: number | null }
  | { kind: "error"; id: string; ts: number; message: string };

export interface AgUiEvent {
  type: string;
  [key: string]: unknown;
}

const SPECIALISTS: Record<string, SpecialistLabel> = {
  rag_agent: "RAG",
  finance_agent: "FINANCE",
  portfolio_agent: "PORTFOLIO",
  browser_agent: "BROWSER",
  email_agent: "EMAIL",
  filesystem_agent: "FILES",
  memory_agent: "MEMORY",
};

function readTotalTokens(usage: unknown): number | null {
  if (!usage || typeof usage !== "object") return null;
  const u = usage as Record<string, unknown>;
  const num = (v: unknown) => (typeof v === "number" ? v : undefined);
  const total = num(u.totalTokens) ?? num(u.total_tokens);
  if (total !== undefined) return total;
  const input = num(u.inputTokens) ?? num(u.input_tokens);
  const output = num(u.outputTokens) ?? num(u.output_tokens);
  return input !== undefined || output !== undefined ? (input ?? 0) + (output ?? 0) : null;
}

export function reduceActivity(items: DeskActivity[], event: AgUiEvent, now: number): DeskActivity[] {
  const id = `${event.type}-${now}-${items.length}`;
  switch (event.type) {
    case "STEP_STARTED": {
      const label = SPECIALISTS[String(event.stepName)];
      return label ? [...items, { kind: "specialist", id, ts: now, label }] : items;
    }
    case "TOOL_CALL_START":
      return [
        ...items,
        { kind: "tool", id, ts: now, toolCallId: String(event.toolCallId), name: String(event.toolCallName), status: "running" },
      ];
    case "TOOL_CALL_END":
      return items.map((it) =>
        it.kind === "tool" && it.toolCallId === event.toolCallId && it.status === "running"
          ? { ...it, status: "done", durationMs: now - it.ts }
          : it,
      );
    case "RUN_FINISHED": {
      const outcome = event.outcome as { type?: string } | undefined;
      if (outcome?.type === "interrupt") return [...items, { kind: "awaiting", id, ts: now }];
      return [...items, { kind: "done", id, ts: now, totalTokens: readTotalTokens(event.usage) }];
    }
    case "RUN_ERROR":
      return [...items, { kind: "error", id, ts: now, message: String(event.message ?? "Run failed") }];
    default:
      return items;
  }
}
