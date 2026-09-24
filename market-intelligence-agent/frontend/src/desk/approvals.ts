// Reading HumanInTheLoopMiddleware interrupts as surfaced by ag-ui-langgraph:
// interrupt.metadata.langgraph.raw = {action_requests, review_configs}.

export type DecisionType = "approve" | "edit" | "reject";

export interface ActionRequest {
  name: string;
  args: Record<string, unknown>;
  description?: string;
}

export type Decision =
  | { type: "approve" }
  | { type: "edit"; edited_action: { name: string; args: Record<string, unknown> } }
  | { type: "reject"; message?: string };

export interface PendingApproval {
  requests: ActionRequest[];
  allowed: DecisionType[][];
}

export const EDITABLE_FIELDS: Record<string, string[]> = {
  send_email: ["recipient", "subject", "body"],
  write_file: ["path", "content"],
  save_memory: ["key", "value"],
};

const ALL: DecisionType[] = ["approve", "edit", "reject"];

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

export function readApproval(interrupt: unknown): PendingApproval {
  const raw =
    isRecord(interrupt) && isRecord(interrupt.metadata) && isRecord(interrupt.metadata.langgraph)
      ? interrupt.metadata.langgraph.raw
      : undefined;
  if (!isRecord(raw) || !Array.isArray(raw.action_requests)) return { requests: [], allowed: [] };

  const requests = raw.action_requests.filter(
    (r): r is ActionRequest => isRecord(r) && typeof r.name === "string" && isRecord(r.args),
  );
  const configs = Array.isArray(raw.review_configs) ? raw.review_configs.filter(isRecord) : [];
  const allowed = requests.map((r) => {
    const cfg = configs.find((c) => c.action_name === r.name);
    const list = Array.isArray(cfg?.allowed_decisions)
      ? cfg.allowed_decisions.filter((d): d is DecisionType => ALL.includes(d as DecisionType))
      : [];
    return list.length ? list : [...ALL];
  });
  return { requests, allowed };
}
