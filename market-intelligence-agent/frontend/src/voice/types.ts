export type VoicePhase =
  | "connecting"
  | "listening"
  | "analyzing"
  | "speaking"
  | "approval_required"
  | "disconnected"
  | "error";

export type VoiceActivityKind =
  | "specialist_started"
  | "tool_started"
  | "tool_finished"
  | "approval_required"
  | "run_finished"
  | "run_error";

export interface VoiceActivityEvent {
  sequence: number;
  run_id: string;
  kind: VoiceActivityKind;
  name: string | null;
  tool_call_id: string | null;
  duration_ms: number | null;
  message: string | null;
}

export interface VoicePendingApproval {
  interrupt_id: string;
  action_requests: Record<string, unknown>[];
  review_configs: Record<string, unknown>[];
}

export interface VoiceState {
  phase: VoicePhase;
  sequence: number;
  events: VoiceActivityEvent[];
  pending: VoicePendingApproval | null;
  error: string | null;
}

export interface VoiceSession {
  session_id: string;
  sdp: string;
}

export interface VoiceDecision {
  type: "approve" | "reject" | "edit";
  message?: string;
  edited_action?: Record<string, unknown>;
}

export interface VoiceDecisionResult {
  status: "applied" | "already_applied";
  response: string | null;
}
