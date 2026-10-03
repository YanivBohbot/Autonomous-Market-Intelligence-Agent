import { useState, useRef, type FormEvent, type KeyboardEvent } from "react";
import { Routes, Route } from "react-router-dom";
import { Header } from "./components/Header";
import { ChatPane } from "./components/ChatPane";
import { ActivityRail } from "./components/ActivityRail";
import { ApprovalCard } from "./components/ApprovalCard";
import { VoicePanel } from "./components/VoicePanel";
import { useChatStream } from "./hooks/useChatStream";
import { newThreadId } from "./lib/api";
import { DeskView } from "./desk/DeskView";

function ClassicChat({ threadId }: { threadId: string }) {
  const [input, setInput] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { messages, activity, streaming, pending, send, resolvePending } = useChatStream(threadId);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    submitQuery();
  }
  function submitQuery() {
    const q = input.trim();
    if (!q || streaming || pending) return;
    setInput("");
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
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 120) + "px";
  }
  const inputDisabled = streaming || !!pending;

  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-hidden">
          <ChatPane messages={messages} streaming={streaming} />
        </div>
        {pending && (
          <div className="border-t border-terminal-border px-4 py-3">
            <ApprovalCard threadId={threadId} pending={pending} onResolved={(text, still) => resolvePending(text, still)} />
          </div>
        )}
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
              <button type="submit" disabled={inputDisabled || !input.trim()} className="rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none">
                {streaming ? <span className="animate-pulse">…</span> : "Send"}
              </button>
              <button type="button" onClick={() => setVoiceOpen((v) => !v)} className={`rounded-xl border px-3 py-2.5 font-mono text-sm transition-all ${voiceOpen ? "border-terminal-accent/50 bg-terminal-accent/10 text-terminal-accent" : "border-terminal-border text-terminal-muted hover:border-terminal-accent/40 hover:text-terminal-text"}`} title="Toggle voice">
                🎤
              </button>
            </div>
          </form>
          <div className="px-4 pb-2">
            <span className="font-mono text-[10px] text-terminal-muted">Enter to send · Shift+Enter for newline</span>
          </div>
        </div>
        {voiceOpen && <VoicePanel threadId={threadId} />}
      </main>
      <ActivityRail activity={activity} />
    </div>
  );
}

export default function App() {
  const [threadId, setThreadId] = useState(newThreadId);

  function onNewSession() {
    setThreadId(newThreadId());
  }

  return (
    <div className="flex h-full flex-col bg-terminal-bg">
      <Header threadId={threadId} onNewSession={onNewSession} />
      <Routes>
        <Route path="/" element={<DeskView key={threadId} threadId={`desk_${threadId}`} />} />
        <Route path="/classic" element={<ClassicChat threadId={threadId} />} />
        <Route path="/data" element={<div>Data</div>} />
      </Routes>
    </div>
  );
}
