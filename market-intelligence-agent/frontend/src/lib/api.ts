import type { ApproveResponse, HealthResponse } from "./types";

// In dev, Vite proxies these paths to the backend, so "" (same origin) works.
export const API_BASE = "";

export async function getHealth(base = API_BASE): Promise<HealthResponse> {
  const res = await fetch(`${base}/health`);
  if (!res.ok) throw new Error(`health ${res.status}`);
  return res.json();
}

export async function postApprove(
  threadId: string,
  approved: boolean,
  base = API_BASE,
): Promise<ApproveResponse> {
  const res = await fetch(`${base}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, approved }),
  });
  if (!res.ok) throw new Error(`approve ${res.status}: ${await res.text()}`);
  return res.json();
}

export function newThreadId(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `web_session_${rand}`;
}

export async function uploadToWorkspace(file: File, base = API_BASE): Promise<{ path: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${base}/copilot/uploads`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`upload ${res.status}: ${await res.text()}`);
  return res.json();
}
