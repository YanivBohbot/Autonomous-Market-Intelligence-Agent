import { API_BASE } from "../lib/api";

export type Conversation = { id: string; title: string; created_at: string; updated_at: string };

export async function listConversations(q?: string, base = API_BASE): Promise<Conversation[]> {
  const qs = q && q.trim() ? `?q=${encodeURIComponent(q.trim())}` : "";
  const res = await fetch(`${base}/conversations${qs}`);
  if (!res.ok) throw new Error(`conversations ${res.status}`);
  return res.json();
}

export async function renameConversation(id: string, title: string, base = API_BASE): Promise<Conversation> {
  const res = await fetch(`${base}/conversations/${encodeURIComponent(id)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`rename ${res.status}`);
  return res.json();
}

export async function deleteConversation(id: string, base = API_BASE): Promise<void> {
  const res = await fetch(`${base}/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`delete ${res.status}`);
}
