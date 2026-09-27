import { useState } from "react";
import type { DisplayPayload } from "./types";

export function RagSourceCards({ display }: { display: Extract<DisplayPayload, { type: "rag_sources" }> }) {
  return (
    <div className="flex flex-col gap-1.5">
      {display.sources.map((s, i) => (
        <SourceCard key={i} source={s} />
      ))}
    </div>
  );
}

function SourceCard({ source }: { source: { filename: string; page: string; excerpt: string } }) {
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
