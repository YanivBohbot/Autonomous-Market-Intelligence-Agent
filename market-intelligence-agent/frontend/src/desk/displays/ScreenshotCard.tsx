import type { DisplayPayload } from "./types";

export function ScreenshotCard({ display }: { display: Extract<DisplayPayload, { type: "screenshot" }> }) {
  return (
    <div className="overflow-hidden rounded-xl border border-terminal-border bg-terminal-panel p-2">
      <a href={display.url} target="_blank" rel="noreferrer">
        <img src={display.url} alt="Browser screenshot" className="w-full rounded" />
      </a>
    </div>
  );
}
