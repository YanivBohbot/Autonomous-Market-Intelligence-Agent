import { useId, useRef, type ReactElement, type RefObject } from "react";
import type { Theme } from "../theme";
import { Icon } from "../ui/Icon";
import { useDialogFocus } from "./ResponsiveRail";

function ComingSoon() {
  return (
    <span className="rounded-full bg-blue-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-blue-700 dark:bg-blue-950/50 dark:text-blue-300">
      Coming soon
    </span>
  );
}

function SettingRow({ label, children }: { label: string; children: ReactElement }) {
  return (
    <div className="space-y-2 rounded-xl border border-terminal-border bg-surface-soft p-3">
      <div className="flex items-center justify-between gap-3">
        <label className="text-xs font-semibold text-terminal-muted">{label}</label>
        <ComingSoon />
      </div>
      {children}
    </div>
  );
}

export function ProfilePreview({
  open,
  onClose,
  theme,
  openerRef,
}: {
  open: boolean;
  onClose: () => void;
  theme: Theme;
  openerRef: RefObject<HTMLButtonElement | null>;
}): ReactElement | null {
  const dialogRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  useDialogFocus({ open, onClose, openerRef, containerRef: dialogRef, initialFocusRef: closeRef });

  if (!open) return null;

  const controlClass = "w-full rounded-lg border border-terminal-border bg-surface-elevated px-3 py-2 text-sm text-terminal-text disabled:cursor-not-allowed disabled:opacity-70";

  return (
    <div className="fixed inset-0 z-[70]">
      <div className="absolute inset-0 bg-slate-950/40 backdrop-blur-[1px]" aria-hidden="true" onClick={onClose} />
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="absolute inset-y-0 right-0 flex w-full max-w-sm flex-col border-l border-terminal-border bg-surface-elevated shadow-2xl"
      >
        <header className="flex items-center justify-between border-b border-terminal-border px-5 py-4">
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-brand-blue">Account preview</p>
            <h2 id={titleId} className="mt-1 text-lg font-semibold text-terminal-text">Profile</h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            aria-label="Close Profile"
            onClick={onClose}
            className="grid h-9 w-9 place-items-center rounded-lg text-terminal-muted transition-colors hover:bg-surface-soft hover:text-terminal-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue"
          >
            <Icon name="close" />
          </button>
        </header>

        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-5">
          <div className="flex items-center gap-3 rounded-2xl border border-terminal-border bg-surface-soft p-4">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-blue-600 text-sm font-bold text-white">DO</span>
            <div>
              <p className="font-semibold text-terminal-text">Desk Operator</p>
              <p className="text-xs text-terminal-muted">Multi-Agent Finance Desk</p>
            </div>
          </div>

          <div className="space-y-3" aria-label="Future profile settings">
            <SettingRow label="Theme">
              <select aria-label="Theme" defaultValue={theme} disabled className={controlClass}>
                <option value="light">Light</option>
                <option value="dark">Dark</option>
              </select>
            </SettingRow>
            <SettingRow label="Language">
              <select aria-label="Language" defaultValue="English" disabled className={controlClass}>
                <option>English</option>
              </select>
            </SettingRow>
            <SettingRow label="Default market">
              <select aria-label="Default market" defaultValue="United States" disabled className={controlClass}>
                <option>United States</option>
              </select>
            </SettingRow>
            <SettingRow label="Refresh interval">
              <select aria-label="Refresh interval" defaultValue="60 seconds" disabled className={controlClass}>
                <option>60 seconds</option>
              </select>
            </SettingRow>
            <SettingRow label="Notifications">
              <div className="flex items-center gap-2">
                <input id="profile-notifications" aria-label="Notifications" type="checkbox" disabled className="h-4 w-4 rounded border-terminal-border" />
                <span className="text-sm text-terminal-muted">Market and agent alerts</span>
              </div>
            </SettingRow>
          </div>
        </div>
      </section>
    </div>
  );
}
