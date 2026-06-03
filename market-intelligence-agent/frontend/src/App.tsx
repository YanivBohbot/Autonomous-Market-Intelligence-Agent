import { useState, type FormEvent } from "react";
import { Header } from "./components/Header";
import { ChatPane } from "./components/ChatPane";
import { ActivityRail } from "./components/ActivityRail";
import { ApprovalCard } from "./components/ApprovalCard";
import { VoicePanel } from "./components/VoicePanel";
import { useChatStream } from "./hooks/useChatStream";
import { newThreadId } from "./lib/api";

export default function App() {
  const [threadId, setThreadId] = useState(newThreadId);
  const [input, setInput] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const { messages, activity, streaming, pending, send, resolvePending, reset } =
    useChatStream(threadId);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q || streaming || pending) return;
    setInput("");
    void send(q);
  }

  function onNewSession() {
    setThreadId(newThreadId());
    reset();
  }

  return (
    <div className="flex h-full flex-col">
      <Header threadId={threadId} onNewSession={onNewSession} />
      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <ChatPane messages={messages} streaming={streaming} />
          </div>

          {pending && (
            <div className="px-4 pb-2">
              <ApprovalCard
                threadId={threadId}
                pending={pending}
                onResolved={(text, still) => resolvePending(text, still)}
              />
            </div>
          )}

          <form onSubmit={onSubmit} className="flex gap-2 border-t border-terminal-border p-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={streaming || !!pending}
              placeholder="Ask the agent…"
              className="flex-1 rounded border border-terminal-border bg-terminal-bg px-3 py-2 font-mono text-sm outline-none focus:border-terminal-accent disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={streaming || !!pending}
              className="rounded bg-terminal-accent px-4 py-2 text-sm font-semibold text-terminal-bg disabled:opacity-50"
            >
              Send
            </button>
            <button
              type="button"
              onClick={() => setVoiceOpen((v) => !v)}
              className="rounded border border-terminal-border px-3 py-2 text-sm text-terminal-text"
            >
              🎤
            </button>
          </form>

          {voiceOpen && <VoicePanel />}
        </main>

        <ActivityRail activity={activity} />
      </div>
    </div>
  );
}
