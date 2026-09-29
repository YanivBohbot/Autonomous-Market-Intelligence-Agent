import { useMemo, useState } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "../constants";
import type { DisplayPayload } from "./types";

type RagSourcesDisplay = Extract<DisplayPayload, { type: "rag_sources" }>;
type Source = RagSourcesDisplay["sources"][number];

const CITATION = /\[Source: (.*?), page (.*?)\]/g;

function citedKeys(text: string): Set<string> {
  const keys = new Set<string>();
  for (const m of text.matchAll(CITATION)) keys.add(`${m[1].trim()}|${m[2].trim()}`);
  return keys;
}

// Narrows the card to the source(s) the reply actually cites (e.g.
// "[Source: Amazon-2024-10K.pdf, page 50]"), instead of every chunk
// search_knowledge_base retrieved (k=4 by default) regardless of whether the
// model used it. Falls back to every source if the reply hasn't streamed a
// recognizable citation yet (or cites something that doesn't match), so the
// card never goes empty.
function useCitedSources(toolCallId: string | undefined, sources: Source[]): Source[] {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const messages = agent.messages;
  return useMemo(() => {
    if (!toolCallId) return sources;
    const toolIdx = messages.findIndex(
      (m) => m.role === "tool" && (m as { toolCallId?: string }).toolCallId === toolCallId,
    );
    if (toolIdx === -1) return sources;
    const reply = messages
      .slice(toolIdx + 1)
      .find((m) => m.role === "assistant" && typeof m.content === "string" && m.content.length > 0);
    if (!reply || typeof reply.content !== "string") return sources;
    const cited = citedKeys(reply.content);
    if (cited.size === 0) return sources;
    const filtered = sources.filter((s) => cited.has(`${s.filename}|${s.page}`));
    return filtered.length > 0 ? filtered : sources;
  }, [messages, toolCallId, sources]);
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
