import { useEffect, useState } from "react";
import { getHealth } from "../lib/api";

export function Header({ threadId, onNewSession }: { threadId: string; onNewSession: () => void }) {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string>("");

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const h = await getHealth();
        if (active) { setHealthy(h.status === "ok" || h.status === "healthy"); setVersion(h.version); }
      } catch {
        if (active) setHealthy(false);
      }
    };
    check();
    const id = setInterval(check, 10000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const dot = healthy === null ? "bg-terminal-muted" : healthy ? "bg-terminal-accent" : "bg-terminal-danger";

  return (
    <header className="flex items-center justify-between border-b border-terminal-border bg-terminal-panel px-4 py-2">
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
        <span className="font-mono text-sm font-semibold">MIA · Dev Console</span>
        {version && <span className="font-mono text-xs text-terminal-muted">v{version}</span>}
      </div>
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-terminal-muted">{threadId}</span>
        <button
          onClick={onNewSession}
          className="rounded border border-terminal-border px-2 py-1 font-mono text-xs text-terminal-text hover:border-terminal-accent"
        >
          New session
        </button>
      </div>
    </header>
  );
}
