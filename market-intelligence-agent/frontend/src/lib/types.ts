export type Role = "user" | "assistant" | "error";

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
}

export interface ActivityItem {
  id: string;
  node: string;
  toolCalls: string[] | null;
  ts: number;
}

export interface PendingAction {
  action: string;
  nextStep: string;
}

export interface ApproveResponse {
  response: string;
  status: "completed" | "interrupted";
  next_step: string | null;
}

export interface HealthResponse {
  status: string;
  version: string;
}
