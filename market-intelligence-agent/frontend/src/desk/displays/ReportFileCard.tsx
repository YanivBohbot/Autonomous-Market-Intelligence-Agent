import type { DisplayPayload } from "./types";

export function ReportFileCard({ display }: { display: Extract<DisplayPayload, { type: "report_file" }> }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-terminal-border bg-terminal-panel p-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" className="shrink-0 text-terminal-accent">
          <path d="M6 2h9l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z" stroke="currentColor" strokeWidth="1.5" />
          <path d="M14 2v5h5" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        <span className="truncate font-mono text-xs text-terminal-text">{display.filename}</span>
      </div>
      <a
        href={display.url}
        download
        className="shrink-0 rounded-lg border border-terminal-accent/40 px-3 py-1.5 font-mono text-xs text-terminal-accent hover:bg-terminal-accent/10"
      >
        Download
      </a>
    </div>
  );
}
