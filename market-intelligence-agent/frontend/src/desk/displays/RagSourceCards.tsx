import { useState } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "../constants";
import type { DisplayPayload } from "./types";

type RagSourcesDisplay = Extract<DisplayPayload, { type: "rag_sources" }>;
type Source = RagSourcesDisplay["sources"][number];
type AgentMessage = { role: string; content?: unknown; toolCallId?: string };

const CITATION = /\[Source: (.*?), page (.*?)\]/g;

function citedKeys(text: string): Set<string> {
  const keys = new Set<string>();
  for (const m of text.matchAll(CITATION)) keys.add(`${m[1].trim()}|${m[2].trim()}`);
  return keys;
}

// Narrows the card to the source(s) the reply actually cites (e.g.
// "[Source: Amazon-2024-10K.pdf, page 50]"), instead of every chunk
// search_knowledge_base retrieved (k=4 by default), most of which the model
// never references. Reads agent.messages directly at render time rather
// than subscribing to the event stream — by the time this card mounts,
// status is already "complete" and the run's final text is already in
// agent.messages (mounting happens right as the run finishes, confirmed
// live), so there's nothing left to stream in. Scans the whole turn (every
// assistant message back to the nearest preceding user message), not just
// what follows the tool result in array order — this backend appends the
// ToolMessage AFTER the assistant's final text, not before, so "after the
// tool call" missed every citation. Falls back to every source if nothing
// recognizable is cited.
function useCitedSources(toolCallId: string | undefined, sources: Source[]): Source[] {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const messages = agent.messages as AgentMessage[];
  if (!toolCallId) return sources;
  const toolIdx = messages.findIndex((m) => m.role === "tool" && m.toolCallId === toolCallId);
  if (toolIdx === -1) return sources;
  let turnStart = toolIdx;
  while (turnStart > 0 && messages[turnStart - 1].role !== "user") turnStart--;
  let replyText = "";
  for (const m of messages.slice(turnStart)) {
    if (m.role === "assistant" && typeof m.content === "string" && m.content.length > 0) replyText += m.content;
  }
  const cited = citedKeys(replyText);
  if (cited.size === 0) return sources;
  const filtered = sources.filter((s) => cited.has(`${s.filename}|${s.page}`));
  return filtered.length > 0 ? filtered : sources;
}

export function RagSourceCards({ display, toolCallId }: { display: RagSourcesDisplay; toolCallId?: string }) {
  const sources = useCitedSources(toolCallId, display.sources);
  return (
    <div className="flex flex-col gap-1.5">
      {sources.map((s, i) => (
        <SourceCard key={i} source={s} />
      ))}
    </div>
  );
}

function SourceCard({ source }: { source: Source }) {
  const [open, setOpen] = useState(false);
  return (
    <button
      type="button"
      onClick={() => setOpen((v) => !v)}
      className="rounded-xl border border-terminal-border bg-terminal-panel p-2.5 text-left font-mono text-xs text-terminal-text hover:border-terminal-accent/40"
    >
      <div className="text-terminal-muted">
        {source.filename} · page {source.page}
      </div>
      {open && <div className="mt-1.5">{source.excerpt}</div>}
    </button>
  );
}
