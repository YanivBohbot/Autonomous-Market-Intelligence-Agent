import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage } from "../lib/types";

function UserBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-end animate-fade-in-up">
      <div className="max-w-[75%] rounded-xl rounded-br-sm border border-terminal-user-border/40 bg-terminal-user px-4 py-2.5 shadow-inner-glow">
        <p className="font-mono text-sm text-terminal-text leading-relaxed">{content}</p>
      </div>
    </div>
  );
}

function AssistantBubble({
  content,
  isStreaming,
}: {
  content: string;
  isStreaming: boolean;
}) {
  return (
    <div className="flex justify-start animate-fade-in-up">
      <div className="max-w-[80%]">
        <div className="mb-1.5 flex items-center gap-1.5">
          <span className="h-1 w-1 rounded-full bg-terminal-accent" />
          <span className="font-mono text-[10px] uppercase tracking-widest text-terminal-muted">
            agent
          </span>
        </div>
        <div className="rounded-xl rounded-tl-sm border border-terminal-border bg-terminal-panel px-4 py-2.5 shadow-inner-glow">
          <div className="chat-prose text-terminal-text">
            <ReactMarkdown>{content}</ReactMarkdown>
            {isStreaming && content.length === 0 && (
              <span className="inline-block h-3 w-0.5 animate-blink-caret bg-terminal-accent" />
            )}
          </div>
          {isStreaming && content.length > 0 && (
            <span className="mt-1 inline-block h-3 w-0.5 animate-blink-caret bg-terminal-accent" />
          )}
        </div>
      </div>
    </div>
  );
}

function ErrorBubble({ content }: { content: string }) {
  return (
    <div className="flex justify-start animate-fade-in-up">
      <div className="max-w-[80%] rounded-xl border border-terminal-danger/40 bg-terminal-danger-dim/30 px-4 py-2.5">
        <div className="mb-1 flex items-center gap-1.5">
          <span className="font-mono text-[10px] uppercase tracking-widest text-terminal-danger">
            error
          </span>
        </div>
        <p className="font-mono text-xs text-terminal-danger/80">{content}</p>
      </div>
    </div>
  );
}

export function ChatPane({
  messages,
  streaming,
}: {
  messages: ChatMessage[];
  streaming: boolean;
}) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(
    () => endRef.current?.scrollIntoView({ behavior: "smooth" }),
    [messages],
  );

  if (messages.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4 px-6">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex h-10 w-10 items-center justify-center rounded-full border border-terminal-border bg-terminal-panel">
            <span className="font-mono text-sm text-terminal-accent">▸</span>
          </div>
          <p className="font-mono text-sm font-medium text-terminal-text">
            Market Intelligence Agent
          </p>
          <p className="font-mono text-xs text-terminal-muted max-w-xs">
            Ask about stocks, companies, or market trends. Try:
          </p>
        </div>
        <div className="flex flex-col gap-1.5 w-full max-w-sm">
          {[
            '"What\'s AMZN trading at?"',
            '"Summarize NVDA\'s recent news"',
            '"Compare AAPL and MSFT this month"',
          ].map((example) => (
            <div
              key={example}
              className="rounded-lg border border-terminal-border bg-terminal-panel px-3 py-2 font-mono text-xs text-terminal-muted"
            >
              {example}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 overflow-y-auto p-4 pb-2">
      {messages.map((m, i) => {
        const isLastAssistant =
          m.role === "assistant" && i === messages.length - 1;
        if (m.role === "user") return <UserBubble key={m.id} content={m.content} />;
        if (m.role === "error") return <ErrorBubble key={m.id} content={m.content} />;
        return (
          <AssistantBubble
            key={m.id}
            content={m.content}
            isStreaming={streaming && isLastAssistant}
          />
        );
      })}
      <div ref={endRef} />
    </div>
  );
}
