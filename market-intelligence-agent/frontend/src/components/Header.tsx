import { useEffect, useState } from "react";
import { getHealth } from "../lib/api";

interface HeaderProps {
  threadId: string;
  onNewSession: () => void;
}

export function Header({ threadId, onNewSession }: HeaderProps) {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string>("");

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const h = await getHealth();
        if (active) {
          setHealthy(h.status === "ok" || h.status === "healthy");
          setVersion(h.version);
        }
      } catch {
        if (active) setHealthy(false);
      }
    };
    check();
    const id = setInterval(check, 10000);
    return () => {
      active = false;
      clearInterval(id);
    };
  }, []);

  const dotClass =
    healthy === null
      ? "bg-terminal-muted"
      : healthy
        ? "bg-terminal-accent animate-pulse-dot shadow-glow-green"
        : "bg-terminal-danger shadow-glow-red";

  return (
    <header className="scan-lines flex items-center justify-between border-b border-terminal-border bg-terminal-panel px-4 py-2.5 shadow-inner-glow">
      {/* Left: brand + status */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${dotClass}`} />
          <span className="font-mono text-sm font-semibold text-terminal-muted">
            MIA · Dev Console
          </span>
        </div>
        {version && (
          <span className="rounded border border-terminal-border px-1.5 py-0.5 font-mono text-[10px] text-terminal-muted">
            v{version}
          </span>
        )}
        {healthy === false && (
          <span className="rounded bg-terminal-danger/10 px-2 py-0.5 font-mono text-[10px] text-terminal-danger">
            backend offline
          </span>
        )}
      </div>

      {/* Right: session info + controls */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1.5 rounded border border-terminal-border bg-terminal-bg px-2.5 py-1">
          <span className="font-mono text-[10px] text-terminal-muted">session</span>
          <span className="font-mono text-[10px] text-terminal-accent">{threadId}</span>
        </div>
        <button
          onClick={onNewSession}
          className="rounded border border-terminal-border bg-terminal-bg px-3 py-1 font-mono text-xs text-terminal-muted transition-all hover:border-terminal-accent hover:text-terminal-accent"
        >
          + New session
        </button>
      </div>
    </header>
  );
}
