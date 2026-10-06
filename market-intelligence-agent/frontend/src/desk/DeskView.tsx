import { useEffect, useMemo } from "react";
import { CopilotChat, CopilotKitProvider, HttpAgent, useConfigureSuggestions } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { MARKET_DESK_AGENT_ID, MARKET_DESK_URL } from "./constants";
import { DeskActivityRail } from "./DeskActivityRail";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { useDeskInterrupt } from "./useDeskInterrupt";
import { useToolDisplay } from "./displays/useToolDisplay";
import { getThreadHistory, uploadToWorkspace } from "../lib/api";
import { useIntelligenceSlot } from "../layout/IntelligenceSlot";

// Market Desk: CopilotKit v2 talking AG-UI straight to FastAPI (no runtime).
// Remounted per thread by App (key={threadId}), so New session starts clean.
export function DeskView({ threadId }: { threadId: string }) {
  const agent = useMemo(() => new HttpAgent({ url: MARKET_DESK_URL }), []);

  // CopilotChat never fetches a thread's prior messages on its own --
  // threadId is outgoing-request metadata only (see the Known limitation
  // note in docs/superpowers/specs/2026-10-04-clients-workspace-design.md).
  // Seed them here on mount so revisiting a thread (e.g. a client's
  // deterministic clients_<id> thread) shows the earlier conversation
  // before the user types anything, instead of only after their next
  // message triggers a MESSAGES_SNAPSHOT.
  useEffect(() => {
    let active = true;
    getThreadHistory(threadId)
      .then((history) => {
        if (active && history.length > 0) agent.setMessages(history);
      })
      .catch(() => {
        // No history yet (new thread) or the fetch failed -- the chat
        // still works, it just starts empty, same as before this existed.
      });
    return () => {
      active = false;
    };
  }, [agent, threadId]);

  return (
    <CopilotKitProvider
      agentId={MARKET_DESK_AGENT_ID}
      agents__unsafe_dev_only={{ [MARKET_DESK_AGENT_ID]: agent }}
      // The checkpointer already holds the thread: send only the new message.
      // Re-sending the whole list would re-add messages summarization removed.
      messageFilter={(messages) => messages.slice(-1)}
      showDevConsole={false}
      enableInspector={false}
    >
      <DeskBody threadId={threadId} />
    </CopilotKitProvider>
  );
}

function DeskBody({ threadId }: { threadId: string }) {
  useDeskInterrupt();
  useToolDisplay();
  // Portaled into AppLayout's Intelligence column instead of rendered as a
  // direct sibling -- DeskActivityRail itself is unchanged, only where its
  // DOM lands changes. Must stay inside DeskBody's own CopilotKitProvider
  // subtree (hence rendering the returned portal right here, not lifting
  // it through plain state) since DeskActivityRail calls useAgent, which
  // needs that provider's context.
  const intelligencePortal = useIntelligenceSlot(<DeskActivityRail />);
  useConfigureSuggestions({
    suggestions: [
      { title: "Portfolio value", message: "What is the total value of a client's portfolio?" },
      { title: "Stock price", message: "What is AAPL trading at?" },
      { title: "Concentration risk", message: "Are any clients over-concentrated in one stock?" },
    ],
    available: "always",
  }, []);
  return (
    <>
      {intelligencePortal}
      <main className="relative flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-terminal-border bg-terminal-panel px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-blue-600 dark:text-blue-400">
              Market Desk
            </p>
            <h1 className="mt-0.5 text-base font-semibold tracking-tight text-terminal-text sm:text-lg">
              Research workspace
            </h1>
            <p className="mt-0.5 text-xs text-terminal-muted">
              Multi-agent market research, portfolio analysis, and approved actions.
            </p>
          </div>
          <span className="inline-flex items-center gap-2 rounded-full border border-terminal-border bg-terminal-bg px-3 py-1 text-[11px] font-semibold text-terminal-muted">
            <span className="h-1.5 w-1.5 rounded-full bg-terminal-accent shadow-glow-green" aria-hidden="true" />
            Live intelligence
          </span>
        </header>
        <div className="pointer-events-none absolute inset-x-4 bottom-20 z-50 flex">
          <ThinkingIndicator />
        </div>
        <CopilotChat
          agentId={MARKET_DESK_AGENT_ID}
          threadId={threadId}
          className="finance-desk-chat h-full min-h-0"
          // Same composer bar as Classic (App.tsx): a static bottom bar
          // with a top border and panel background, not a floating pill --
          // CopilotKit's own light-mode styling here was unreadable against
          // a white page, and the two chats should look like one product.
          input={{
            positioning: "static",
            className: "border-t border-terminal-border bg-terminal-panel px-3 py-3",
            textArea:
              "rounded-xl border border-terminal-border bg-terminal-bg px-3.5 py-2.5 font-mono text-sm text-terminal-text placeholder-terminal-muted outline-none transition-colors focus:border-terminal-accent/60",
            sendButton:
              "rounded-xl bg-terminal-accent px-4 py-2.5 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none",
          }}
          attachments={{
            enabled: true,
            maxSize: 20 * 1024 * 1024,
            onUpload: async (file) => {
              const { path } = await uploadToWorkspace(file);
              return {
                type: "url",
                value: path,
                metadata: { filename: file.name, note: `Read this with read_text_file at path ${path} if relevant.` },
              };
            },
          }}
        />
      </main>
    </>
  );
}
