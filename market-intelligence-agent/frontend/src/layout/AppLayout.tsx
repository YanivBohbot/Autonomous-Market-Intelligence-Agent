import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { getHealth } from "../lib/api";
import { getTheme, toggleTheme, type Theme } from "../theme";
import { Icon } from "../ui/Icon";
import { GlobalMarketTicker } from "./GlobalMarketTicker";
import { IntelligenceSlotProvider } from "./IntelligenceSlot";
import { ProfilePreview } from "./ProfilePreview";
import { ResponsiveRail } from "./ResponsiveRail";

const NAV_ITEMS = [
  { to: "/briefing", label: "Briefing", icon: "briefing" },
  { to: "/clients", label: "Clients", icon: "clients" },
  { to: "/research", label: "Research", icon: "research" },
  { to: "/reports", label: "Reports", icon: "reports" },
  { to: "/data", label: "Data", icon: "data" },
] as const;

const controlClass = "inline-flex h-9 items-center justify-center gap-2 rounded-xl border border-terminal-border bg-surface-elevated px-3 text-sm font-medium text-terminal-muted transition-colors hover:border-brand-blue/50 hover:bg-surface-soft hover:text-terminal-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue";

function SystemReady() {
  return (
    <div className="flex h-full min-h-48 flex-col items-center justify-center px-6 text-center">
      <span className="grid h-11 w-11 place-items-center rounded-2xl bg-blue-50 text-brand-blue dark:bg-blue-950/50" aria-hidden="true">
        <Icon name="activity" />
      </span>
      <p className="mt-3 text-sm font-semibold text-terminal-text">System ready</p>
      <p className="mt-1 max-w-52 text-xs leading-relaxed text-terminal-muted">
        Activity will appear after a Research or client workspace run starts.
      </p>
    </div>
  );
}

export function AppLayout() {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [theme, setThemeState] = useState<Theme>("light");
  const [navigationOpen, setNavigationOpen] = useState(false);
  const [activityOpen, setActivityOpen] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const [intelligenceContainer, setIntelligenceContainer] = useState<HTMLDivElement | null>(null);
  const [intelligenceOccupied, setIntelligenceOccupied] = useState(false);
  const navigationOpenerRef = useRef<HTMLButtonElement>(null);
  const activityOpenerRef = useRef<HTMLButtonElement>(null);
  const profileOpenerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    setThemeState(getTheme());
  }, []);

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const health = await getHealth();
        if (active) setHealthy(health.status === "ok" || health.status === "healthy");
      } catch {
        if (active) setHealthy(false);
      }
    };
    void check();
    const intervalId = window.setInterval(() => void check(), 10_000);
    return () => {
      active = false;
      window.clearInterval(intervalId);
    };
  }, []);

  const healthLabel = healthy === null ? "Backend status checking" : healthy ? "Backend online" : "Backend offline";
  const healthTone = healthy === null
    ? "bg-terminal-muted"
    : healthy
      ? "bg-emerald-500 shadow-[0_0_0_3px_rgb(16_185_129_/_0.12)]"
      : "bg-red-500 shadow-[0_0_0_3px_rgb(239_68_68_/_0.12)]";

  return (
    <div className="flex h-full min-h-0 flex-col bg-terminal-bg">
      <header className="flex min-h-16 items-center justify-between gap-3 border-b border-terminal-border bg-surface-elevated px-3 py-2 sm:px-5">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-blue-600 text-sm font-bold tracking-tight text-white shadow-sm">MF</span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-terminal-text sm:text-base">Multi-Agent Finance Desk</p>
            <p className="hidden text-[11px] text-terminal-muted sm:block">Market intelligence workspace</p>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span aria-label={healthLabel} title={healthLabel} className="inline-flex h-9 items-center gap-2 rounded-xl border border-terminal-border bg-surface-soft px-2.5 text-xs font-medium text-terminal-muted">
            <span className={`h-2 w-2 rounded-full ${healthTone}`} aria-hidden="true" />
            <span className="hidden sm:inline">{healthy === null ? "Checking" : healthy ? "Online" : "Offline"}</span>
          </span>
          <button
            type="button"
            onClick={() => setThemeState(toggleTheme())}
            title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
            className={controlClass}
          >
            <Icon name="theme" className="h-4 w-4" />
            <span className="hidden md:inline">{theme === "dark" ? "Light" : "Dark"}</span>
          </button>
          <button ref={profileOpenerRef} type="button" onClick={() => setProfileOpen(true)} className={controlClass} aria-label="Profile">
            <Icon name="profile" className="h-4 w-4" />
            <span className="hidden md:inline">Profile</span>
          </button>
          <button
            ref={navigationOpenerRef}
            type="button"
            aria-label="Open navigation"
            onClick={() => setNavigationOpen(true)}
            className={`${controlClass} xl:hidden`}
          >
            <Icon name="menu" className="h-4 w-4" />
          </button>
          <button
            ref={activityOpenerRef}
            type="button"
            aria-label="Open activity"
            onClick={() => setActivityOpen(true)}
            className={`${controlClass} xl:hidden`}
          >
            <Icon name="activity" className="h-4 w-4" />
          </button>
        </div>
      </header>

      <GlobalMarketTicker />

      <div className="flex min-h-0 flex-1">
        <ResponsiveRail
          open={navigationOpen}
          side="left"
          title="Navigation"
          onClose={() => setNavigationOpen(false)}
          openerRef={navigationOpenerRef}
          className="xl:w-60"
        >
          <nav aria-label="Primary navigation" className="flex h-full flex-col p-3">
            <p className="px-3 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-terminal-muted">Workspace</p>
            <div className="space-y-1">
              {NAV_ITEMS.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  onClick={() => setNavigationOpen(false)}
                  className={({ isActive }) =>
                    `flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue ${
                      isActive
                        ? "bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300"
                        : "text-terminal-muted hover:bg-surface-soft hover:text-terminal-text"
                    }`
                  }
                >
                  <Icon name={item.icon} className="h-4 w-4" />
                  {item.label}
                </NavLink>
              ))}
            </div>

            <div className="mt-auto space-y-2 border-t border-terminal-border pt-3">
              <button type="button" aria-label="Profile settings" onClick={() => { setNavigationOpen(false); setProfileOpen(true); }} className="flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm text-terminal-muted transition-colors hover:bg-surface-soft hover:text-terminal-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue">
                <Icon name="settings" className="h-4 w-4" />
                Profile settings
              </button>
            </div>
          </nav>
        </ResponsiveRail>

        <IntelligenceSlotProvider container={intelligenceContainer} onOccupiedChange={setIntelligenceOccupied}>
          <main className="flex min-h-0 min-w-0 flex-1 flex-col">
            <Outlet />
          </main>
        </IntelligenceSlotProvider>

        <ResponsiveRail
          open={activityOpen}
          side="right"
          title="Agent activity"
          onClose={() => setActivityOpen(false)}
          openerRef={activityOpenerRef}
          className="xl:w-72"
        >
          <div ref={setIntelligenceContainer} data-testid="intelligence-slot" className="h-full min-h-0">
            {!intelligenceOccupied && <SystemReady />}
          </div>
        </ResponsiveRail>
      </div>

      <ProfilePreview open={profileOpen} onClose={() => setProfileOpen(false)} theme={theme} openerRef={profileOpenerRef} />
    </div>
  );
}
