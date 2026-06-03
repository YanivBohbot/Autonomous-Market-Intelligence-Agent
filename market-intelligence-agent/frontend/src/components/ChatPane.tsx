import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage } from "../lib/types";

const roleStyles: Record<ChatMessage["role"], string> = {
  user: "self-end bg-terminal-border/60 text-terminal-text",
  assistant: "self-start bg-terminal-panel text-terminal-text",
  error: "self-start bg-terminal-danger/10 text-terminal-danger border border-terminal-danger/40",
};

export function ChatPane({ messages, streaming }: { messages: ChatMessage[]; streaming: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-terminal-muted">
        <p className="font-mono text-sm">Ask the agent something. e.g. "What's AMZN trading at?"</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 overflow-y-auto p-4">
      {messages.map((m, i) => (
        <div
          key={m.id}
          className={`max-w-[80%] rounded-lg px-3 py-2 text-sm leading-relaxed ${roleStyles[m.role]}`}
        >
          <div className="prose prose-invert prose-sm max-w-none">
            <ReactMarkdown>
              {m.content + (streaming && m.role === "assistant" && i === messages.length - 1 ? " ▌" : "")}
            </ReactMarkdown>
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
