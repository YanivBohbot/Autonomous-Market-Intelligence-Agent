import { useCallback, useEffect, useMemo } from "react";
import { CopilotChat, CopilotChatInput, CopilotKitProvider, HttpAgent, useAgent, useAgentContext, useConfigureSuggestions } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { MARKET_DESK_AGENT_ID, MARKET_DESK_URL } from "./constants";
import { lastCardContext } from "./lastCardContext";
import { DeskActivityRail } from "./DeskActivityRail";
import { ThinkingIndicator } from "./ThinkingIndicator";
import { useDeskInterrupt } from "./useDeskInterrupt";
import { useToolDisplay } from "./displays/useToolDisplay";
import { getThreadHistory, uploadToWorkspace, type ThreadMessage } from "../lib/api";
import { useIntelligenceSlot } from "../layout/IntelligenceSlot";
import { ResearchVoiceApproval } from "../voice/ResearchVoiceApproval";
import { ResearchVoiceProvider, useResearchVoiceContext } from "../voice/ResearchVoiceContext";
import { LiveCaptionBubble } from "../voice/LiveCaptionBubble";
import { useVoiceHistoryRefresh } from "../voice/useVoiceHistoryRefresh";
import { mergeHistory } from "./mergeHistory";
import { ResearchComposer } from "./ResearchComposer";
import { RESEARCH_STARTERS, type StarterSuggestion } from "./starters";

export type DeskViewProps = {
  threadId: string;
  voiceEnabled?: boolean;
  starterSuggestions?: StarterSuggestion[];
  // What the page shows, shared with the agent via useAgentContext.
  agentContext?: AgentContextEntry[];
  // Called after each finished turn (typed or voice), e.g. to refresh history.
  onTurnFinished?: () => void;
};

export type AgentContextEntry = { description: string; value: string };

// Market Desk: CopilotKit v2 talking AG-UI straight to FastAPI (no runtime).
// Remounted per thread by ResearchPage (key={threadId}), so each conversation starts clean.
export function DeskView({
  threadId,
  voiceEnabled = false,
  starterSuggestions = RESEARCH_STARTERS,
  agentContext = [],
  onTurnFinished,
}: DeskViewProps) {
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
      {voiceEnabled ? (
        <ResearchVoiceProvider threadId={threadId} enabled>
          <DeskBody threadId={threadId} agent={agent} starterSuggestions={starterSuggestions} agentContext={agentContext} onTurnFinished={onTurnFinished} />
        </ResearchVoiceProvider>
      ) : (
        <DeskBody threadId={threadId} agent={agent} starterSuggestions={starterSuggestions} agentContext={agentContext} onTurnFinished={onTurnFinished} />
      )}
    </CopilotKitProvider>
  );
}

function DeskBody({
  threadId,
  agent,
  starterSuggestions,
  agentContext,
  onTurnFinished,
}: {
  threadId: string;
  agent: HttpAgent;
  starterSuggestions: StarterSuggestion[];
  agentContext: AgentContextEntry[];
  onTurnFinished?: () => void;
}) {
  const voice = useResearchVoiceContext();
  const setMessages = useCallback(
    (history: ThreadMessage[]) => {
      if (history.length === 0) return;
      agent.setMessages(mergeHistory(agent.messages, history));
      onTurnFinished?.();
    },
    [agent, onTurnFinished],
  );
  const { agent: chatAgent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  useEffect(() => {
    if (!onTurnFinished || !chatAgent?.subscribe) return;
    const sub = chatAgent.subscribe({ onRunFinalized: () => { onTurnFinished(); } });
    return () => sub.unsubscribe();
  }, [chatAgent, onTurnFinished]);
  const { refreshError } = useVoiceHistoryRefresh(threadId, voice?.events, setMessages);
  useDeskInterrupt(voice?.setTypedApprovalPending);
  useToolDisplay();
  // Before the first message only: commit 740ef53 removed suggestions that
  // stayed on screen for the whole conversation ("always").
  useConfigureSuggestions({ suggestions: starterSuggestions, available: "before-first-message" }, [starterSuggestions]);
  // Portaled into AppLayout's Intelligence column instead of rendered as a
  // direct sibling -- DeskActivityRail itself is unchanged, only where its
  // DOM lands changes. Must stay inside DeskBody's own CopilotKitProvider
  // subtree (hence rendering the returned portal right here, not lifting
  // it through plain state) since DeskActivityRail calls useAgent, which
  // needs that provider's context.
  const intelligencePortal = useIntelligenceSlot(
    <DeskActivityRail voiceEvents={voice?.events} />,
  );
  return (
    <>
      {intelligencePortal}
      <LastCardContext />
      <FollowUpSuggestions />
      {agentContext.map((c) => <ContextEntry key={c.description} {...c} />)}
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
        {voice?.pending && (
          <div className="absolute inset-x-4 bottom-24 z-40 max-h-[65%] overflow-y-auto rounded-2xl shadow-xl">
            <ResearchVoiceApproval pending={voice.pending} />
          </div>
        )}
        <div className="pointer-events-none absolute inset-x-4 bottom-24 z-30 flex justify-end">
          <LiveCaptionBubble text={voice?.liveCaption ?? ""} />
        </div>
        {refreshError && (
          <p role="alert" className="mx-4 mb-1 rounded-lg border border-terminal-warn/40 bg-terminal-warn/10 px-3 py-1.5 text-xs text-terminal-warn">
            {refreshError}
          </p>
        )}
        <CopilotChat
          agentId={MARKET_DESK_AGENT_ID}
          threadId={threadId}
          className="finance-desk-chat h-full min-h-0"
          // CopilotKit's runtime accepts any compatible input component, but
          // its 1.74 type also requires the default component's static slots.
          input={ResearchComposer as typeof CopilotChatInput}
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

// One useAgentContext call per component, so the hook count stays stable
// when the page's context list changes length.
function ContextEntry({ description, value }: AgentContextEntry) {
  useAgentContext({ description, value });
  return null;
}

function LastCardContext() {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const value = lastCardContext((agent?.messages ?? []) as { role?: string; content?: unknown }[]);
  useAgentContext({ description: "Most recent card shown in the chat", value: value ?? "none" });
  return null;
}

// Follow-ups written by the graph's suggest_followups node (agent state, via
// the AG-UI STATE_SNAPSHOT); replace the starters once the chat has begun.
function FollowUpSuggestions() {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const suggestions = (agent?.state as { suggestions?: StarterSuggestion[] } | undefined)?.suggestions ?? [];
  useConfigureSuggestions(
    suggestions.length ? { suggestions, available: "after-first-message" } : null,
    [JSON.stringify(suggestions)],
  );
  return null;
}
