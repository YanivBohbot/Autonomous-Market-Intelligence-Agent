import { useState, useRef, type FormEvent, type KeyboardEvent } from "react";
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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { messages, activity, streaming, pending, send, resolvePending, reset } =
    useChatStream(threadId);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submitQuery();
  }

  function submitQuery() {
    const q = input.trim();
    if (!q || streaming || pending) return;
    setInput("");
    // Reset textarea height
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    void send(q);
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitQuery();
    }
  }

  function onTextareaChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setInput(e.target.value);
    // Auto-resize up to ~120px
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }

  function onNewSession() {
    setThreadId(newThreadId());
    reset();
  }

  const inputDisabled = streaming || !!pending;

  return (
    <div className="flex h-full flex-col bg-terminal-bg">
      <Header threadId={threadId} onNewSession={onNewSession} />

      {/* Main content area */}
      <div className="flex min-h-0 flex-1">
        {/* Chat column */}
        <main className="flex min-w-0 flex-1 flex-col">
          {/* Message list — fills available height */}
          <div className="min-h-0 flex-1 overflow-hidden">
            <ChatPane messages={messages} streaming={streaming} />
          </div>

          {/* HITL approval card — shown when pending */}
          {pending && (
            <div className="border-t border-terminal-border px-4 py-3">
              <ApprovalCard
                threadId={threadId}
                pending={pending}
                onResolved={(text, still) => resolvePending(text, still)}
              />
            </div>
          )}

          {/* Input bar */}
          <div className="border-t border-terminal-border bg-terminal-panel">
            <form onSubmit={onSubmit} className="flex items-end gap-2 px-3 py-3">
              <textarea
                ref={textareaRef}
                rows={1}
                value={input}
                onChange={onTextareaChange}
                onKeyDown={onKeyDown}
                disabled={inputDisabled}
                placeholder="Ask the agent…"
                className="flex-1 resize-none overflow-hidden rounded-xl border border-terminal-border bg-terminal-bg px-3.5 py-2.5 font-mono text-sm text-terminal-text placeholder-terminal-muted outline-none transition-colors focus:border-terminal-accent/60 disabled:cursor-not-allowed disabled:opacity-50"
              />
              <div className="flex flex-none items-center gap-1.5 pb-0.5">
                <button
                  type="submit"
                  disabled={inputDisabled || !input.trim()}
                  className="rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
                >
                  {streaming ? (
                    <span className="animate-pulse">…</span>
                  ) : (
                    "Send"
                  )}
                </button>
                <button
                  type="button"
                  onClick={() => setVoiceOpen((v) => !v)}
                  className={`rounded-xl border px-3 py-2.5 font-mono text-sm transition-all ${
                    voiceOpen
                      ? "border-terminal-accent/50 bg-terminal-accent/10 text-terminal-accent"
                      : "border-terminal-border text-terminal-muted hover:border-terminal-accent/40 hover:text-terminal-text"
                  }`}
                  title="Toggle voice"
                >
                  🎤
                </button>
              </div>
            </form>
            {/* Keyboard hint */}
            <div className="px-4 pb-2">
              <span className="font-mono text-[10px] text-terminal-muted">
                Enter to send · Shift+Enter for newline
              </span>
            </div>
          </div>

          {/* Voice panel — collapsible */}
          {voiceOpen && <VoicePanel />}
        </main>

        {/* Activity rail */}
        <ActivityRail activity={activity} />
      </div>
    </div>
  );
}
