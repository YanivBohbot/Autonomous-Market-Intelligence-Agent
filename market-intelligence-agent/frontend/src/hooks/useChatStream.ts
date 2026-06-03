import { useCallback, useRef, useState } from "react";
import { parseSseBuffer } from "../lib/sse";
import { API_BASE } from "../lib/api";
import type { ActivityItem, ChatMessage, PendingAction } from "../lib/types";

let idCounter = 0;
const nextId = () => `m${Date.now()}_${idCounter++}`;

export function useChatStream(threadId: string, base = API_BASE) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const assistantIdRef = useRef<string | null>(null);

  const appendActivity = useCallback((node: string, toolCalls: string[] | null) => {
    setActivity((prev) => [...prev, { id: nextId(), node, toolCalls, ts: Date.now() }]);
  }, []);

  const send = useCallback(
    async (query: string) => {
      setMessages((prev) => [...prev, { id: nextId(), role: "user", content: query }]);
      const assistantId = nextId();
      assistantIdRef.current = assistantId;
      setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }]);
      setStreaming(true);

      try {
        const res = await fetch(`${base}/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, thread_id: threadId }),
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { events, rest } = parseSseBuffer(buffer);
          buffer = rest;

          for (const ev of events) {
            const data = ev.data as Record<string, unknown>;
            if (ev.event === "token") {
              const tok = String(data.token ?? "");
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: m.content + tok } : m,
                ),
              );
            } else if (ev.event === "node") {
              appendActivity(
                String(data.node ?? "?"),
                (data.tool_calls as string[] | null) ?? null,
              );
            } else if (ev.event === "interrupted") {
              setPending({
                action: String(data.action ?? "Action requires approval."),
                nextStep: String(data.next_step ?? ""),
              });
            } else if (ev.event === "error") {
              setMessages((prev) => [
                ...prev,
                { id: nextId(), role: "error", content: String(data.error ?? "Unknown error") },
              ]);
            }
          }
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: "error", content: (err as Error).message },
        ]);
      } finally {
        setStreaming(false);
      }
    },
    [base, threadId, appendActivity],
  );

  // Called by the approval flow to append the resumed result and update pending.
  const resolvePending = useCallback(
    (responseText: string, stillPending: PendingAction | null) => {
      if (responseText) {
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: "assistant", content: responseText },
        ]);
      }
      setPending(stillPending);
    },
    [],
  );

  const reset = useCallback(() => {
    setMessages([]);
    setActivity([]);
    setPending(null);
    setStreaming(false);
  }, []);

  return { messages, activity, streaming, pending, send, resolvePending, reset };
}
