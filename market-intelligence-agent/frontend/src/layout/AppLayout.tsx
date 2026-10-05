import { useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getHealth } from "../lib/api";
import { getTheme, toggleTheme, type Theme } from "../theme";
import { IntelligenceSlotProvider } from "./IntelligenceSlot";

interface AppLayoutProps {
  threadId: string;
  onNewSession: () => void;
}

const NAV_ITEMS = [
  { to: "/briefing", label: "Briefing" },
  { to: "/clients", label: "Clients" },
  { to: "/research", label: "Research" },
  { to: "/reports", label: "Reports" },
  { to: "/data", label: "Data" },
];

const emptyIntelligence = (
  <aside className="flex h-full w-64 flex-none flex-col items-center justify-center border-l border-terminal-border bg-terminal-panel">
    <span className="font-mono text-[10px] text-terminal-muted">No activity</span>
  </aside>
);

export function AppLayout({ threadId, onNewSession }: AppLayoutProps) {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string>("");
  const [theme, setThemeState] = useState<Theme>("light");
  const [intelligenceContainer, setIntelligenceContainer] = useState<HTMLDivElement | null>(null);
  const [intelligenceOccupied, setIntelligenceOccupied] = useState(false);

  useEffect(() => {
    setThemeState(getTheme());
  }, []);

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
    healthy === null ? "bg-terminal-muted" : healthy ? "bg-terminal-accent animate-pulse-dot shadow-glow-green" : "bg-terminal-danger shadow-glow-red";

  return (
    <div className="flex h-full flex-col bg-terminal-bg">
      <header className="scan-lines flex items-center justify-between border-b border-terminal-border bg-terminal-panel px-4 py-2.5 shadow-inner-glow">
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${dotClass}`} />
            <span className="font-mono text-sm font-semibold text-terminal-muted">MIA · Dev Console</span>
          </div>
          {version && (
            <span className="rounded border border-terminal-border px-1.5 py-0.5 font-mono text-[10px] text-terminal-muted">v{version}</span>
          )}
          {healthy === false && (
            <span className="rounded bg-terminal-danger/10 px-2 py-0.5 font-mono text-[10px] text-terminal-danger">backend offline</span>
          )}
        </div>
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
          <button
            type="button"
            onClick={() => setThemeState(toggleTheme())}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            className="rounded border border-terminal-border bg-terminal-bg px-2.5 py-1 font-mono text-xs text-terminal-muted transition-all hover:border-terminal-accent hover:text-terminal-accent"
          >
            {theme === "dark" ? "☀ Light" : "🌙 Dark"}
          </button>
          <button
            type="button"
            title="Profile (coming soon)"
            className="rounded border border-terminal-border bg-terminal-bg px-2.5 py-1 font-mono text-xs text-terminal-muted"
          >
            Profil
          </button>
        </div>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav className="flex w-48 flex-none flex-col gap-1 border-r border-terminal-border bg-terminal-panel p-2">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `rounded px-3 py-2 font-mono text-xs transition-colors ${
                  isActive ? "bg-terminal-accent/15 text-terminal-accent" : "text-terminal-muted hover:text-terminal-text"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <IntelligenceSlotProvider container={intelligenceContainer} onOccupiedChange={setIntelligenceOccupied}>
          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            <Outlet />
          </main>
        </IntelligenceSlotProvider>
        <div ref={setIntelligenceContainer} className="h-full w-64 flex-none">
          {!intelligenceOccupied && emptyIntelligence}
        </div>
      </div>
    </div>
  );
}
