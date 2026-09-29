import { useEffect, useState } from "react";
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
// search_knowledge_base retrieved (k=4 by default), most of which the model
// never references. Tracks the run's streamed text itself, mirroring
// ThinkingIndicator/DeskActivityRail's agent.subscribe pattern, instead of
// reading agent.messages directly — that array's identity doesn't reliably
// change as tokens stream in, which left an earlier version of this stuck
// showing every source forever. Falls back to every source until a
// recognizable citation has streamed in.
function useCitedSources(sources: Source[]): Source[] {
  const { agent } = useAgent({ agentId: MARKET_DESK_AGENT_ID });
  const [replyText, setReplyText] = useState("");

  useEffect(() => {
    const sub = agent.subscribe({
      onEvent: ({ event }) => {
        const e = event as { type: string; delta?: string };
        if (e.type === "RUN_STARTED") setReplyText("");
        else if (e.type === "TEXT_MESSAGE_CONTENT") setReplyText((prev) => prev + (e.delta ?? ""));
      },
    });
    return () => sub.unsubscribe();
  }, [agent]);

  const cited = citedKeys(replyText);
  if (cited.size === 0) return sources;
  const filtered = sources.filter((s) => cited.has(`${s.filename}|${s.page}`));
  return filtered.length > 0 ? filtered : sources;
}

export function RagSourceCards({ display }: { display: RagSourcesDisplay }) {
  const sources = useCitedSources(display.sources);
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
