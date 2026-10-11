import { API_BASE } from "../lib/api";
import type {
  VoiceDecision,
  VoiceDecisionResult,
  VoiceSession,
  VoiceState,
} from "./types";

async function detailOrStatus(response: Response, fallback: string): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    // Fall back to a concise status when the server did not return JSON.
  }
  return `${fallback} ${response.status}`;
}

export async function createResearchVoiceSession(
  threadId: string,
  sdp: string,
  base = API_BASE,
): Promise<VoiceSession> {
  const response = await fetch(`${base}/gptlive/session`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ sdp, thread_id: threadId, surface: "research" }),
  });
  if (!response.ok) {
    throw new Error(await detailOrStatus(response, "Voice session failed"));
  }
  return response.json();
}

export async function getResearchVoiceState(
  threadId: string,
  after: number,
  base = API_BASE,
): Promise<VoiceState> {
  const response = await fetch(
    `${base}/voice/${encodeURIComponent(threadId)}/state?after=${after}`,
  );
  if (!response.ok) {
    throw new Error(await detailOrStatus(response, "Voice state failed"));
  }
  return response.json();
}

export async function submitResearchVoiceDecision(
  threadId: string,
  interruptId: string,
  decisions: VoiceDecision[],
  base = API_BASE,
): Promise<VoiceDecisionResult> {
  const response = await fetch(`${base}/voice/${encodeURIComponent(threadId)}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ interrupt_id: interruptId, decisions }),
  });
  if (!response.ok) {
    throw new Error(await detailOrStatus(response, "Voice decision failed"));
  }
  return response.json();
}
