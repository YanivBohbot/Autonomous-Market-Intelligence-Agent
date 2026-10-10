// Pure AG-UI event → activity-row reducer for the Market Desk rail.

import type { VoiceActivityEvent } from "../voice/types";

export type SpecialistLabel = "SUPERVISOR" | "RAG" | "FINANCE" | "PORTFOLIO" | "BROWSER" | "EMAIL" | "FILES" | "MEMORY";

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

export function voiceActivityToAgUi(event: VoiceActivityEvent): AgUiEvent {
  switch (event.kind) {
    case "specialist_started":
      return { type: "STEP_STARTED", stepName: event.name ?? "" };
    case "tool_started":
      return {
        type: "TOOL_CALL_START",
        toolCallId: event.tool_call_id ?? `${event.run_id}:${event.sequence}`,
        toolCallName: event.name ?? "tool",
      };
    case "tool_finished":
      return {
        type: "TOOL_CALL_RESULT",
        toolCallId: event.tool_call_id ?? `${event.run_id}:${event.sequence}`,
        durationMs: event.duration_ms,
      };
    case "approval_required":
      return { type: "RUN_FINISHED", outcome: { type: "interrupt" } };
    case "run_finished":
      return { type: "RUN_FINISHED" };
    case "run_error":
      return { type: "RUN_ERROR", message: event.message ?? "Voice processing failed" };
  }
}

export interface ActivityRun {
  id: string;
  startedAt: number;
  items: DeskActivity[];
  status: "running" | "awaiting" | "done" | "error";
}

const SPECIALISTS: Record<string, SpecialistLabel> = {
  supervisor: "SUPERVISOR",
  supervisor_agent: "SUPERVISOR",
  rag_agent: "RAG",
  finance_agent: "FINANCE",
  portfolio_agent: "PORTFOLIO",
  browser_agent: "BROWSER",
  email_agent: "EMAIL",
  filesystem_agent: "FILES",
  memory_agent: "MEMORY",
};

function terminalStatus(item: DeskActivity): ActivityRun["status"] | null {
  if (item.kind === "awaiting" || item.kind === "done" || item.kind === "error") return item.kind;
  return null;
}

export function groupActivityRuns(items: DeskActivity[]): ActivityRun[] {
  const runs: ActivityRun[] = [];
  let current: ActivityRun | null = null;

  for (const item of items) {
    if (!current) {
      current = {
        id: `run-${item.id}`,
        startedAt: item.ts,
        items: [],
        status: "running",
      };
      runs.push(current);
    }

    current.items.push(item);
    const status = terminalStatus(item);
    if (status) {
      current.status = status;
      current = null;
    }
  }

  return runs.reverse();
}

export function humanizeToolName(name: string): string {
  const words = name
    .replace(/^yfinance_/, "")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim()
    .toLowerCase();
  return words ? `${words[0].toUpperCase()}${words.slice(1)}` : "Tool";
}

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

// The same specialist's step can restart within one hop (e.g. when it hands
// back to the supervisor); one badge per specialist per run is enough.
function lastSpecialistInRun(items: DeskActivity[]): SpecialistLabel | undefined {
  for (let i = items.length - 1; i >= 0; i--) {
    const it = items[i];
    if (it.kind === "specialist") return it.label;
    if (it.kind === "done" || it.kind === "awaiting" || it.kind === "error") return undefined;
  }
  return undefined;
}

// A tool that never produced a result (e.g. a rejected call) is over once the
// run is; it gets no duration since it never ran.
function closeRunningTools(items: DeskActivity[]): DeskActivity[] {
  return items.map((it) => (it.kind === "tool" && it.status === "running" ? { ...it, status: "done" } : it));
}

export function reduceActivity(items: DeskActivity[], event: AgUiEvent, now: number): DeskActivity[] {
  const id = `${event.type}-${now}-${items.length}`;
  switch (event.type) {
    case "STEP_STARTED": {
      const label = SPECIALISTS[String(event.stepName)];
      if (!label || lastSpecialistInRun(items) === label) return items;
      return [...items, { kind: "specialist", id, ts: now, label }];
    }
    case "TOOL_CALL_START":
      return [
        ...items,
        { kind: "tool", id, ts: now, toolCallId: String(event.toolCallId), name: String(event.toolCallName), status: "running" },
      ];
    // TOOL_CALL_END only closes the model's argument stream; the tool has run
    // once its result arrives.
    case "TOOL_CALL_RESULT":
      return items.map((it) =>
        it.kind === "tool" && it.toolCallId === event.toolCallId && it.status === "running"
          ? {
              ...it,
              status: "done",
              durationMs:
                typeof event.durationMs === "number"
                  ? event.durationMs
                  : now - it.ts,
            }
          : it,
      );
    case "RUN_FINISHED": {
      const outcome = event.outcome as { type?: string } | undefined;
      // Interrupted: a tool awaiting approval keeps running until it resumes.
      if (outcome?.type === "interrupt") return [...items, { kind: "awaiting", id, ts: now }];
      return [...closeRunningTools(items), { kind: "done", id, ts: now, totalTokens: readTotalTokens(event.usage) }];
    }
    case "RUN_ERROR":
      return [...closeRunningTools(items), { kind: "error", id, ts: now, message: String(event.message ?? "Run failed") }];
    default:
      return items;
  }
}
