import { Icon, type IconName } from "./Icon";

export function Skeleton({ className = "h-4 w-full", label = "Loading" }: { className?: string; label?: string }) {
  return (
    <div role="status" aria-label={label} className={`animate-pulse rounded-lg bg-terminal-border/45 ${className}`}>
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function EmptyState({ title, description, icon = "document" }: { title: string; description?: string; icon?: IconName }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center rounded-2xl border border-dashed border-terminal-border bg-[rgb(var(--surface-soft))] p-6 text-center">
      <span className="grid h-11 w-11 place-items-center rounded-xl bg-blue-50 text-blue-600 dark:bg-blue-950/50 dark:text-blue-300" aria-hidden="true">
        <Icon name={icon} />
      </span>
      <h2 className="mt-3 text-base font-semibold text-terminal-text">{title}</h2>
      {description && <p className="mt-1 max-w-md text-sm text-terminal-muted">{description}</p>}
    </div>
  );
}

export function ErrorState({ title, description, actionLabel, onAction }: { title: string; description?: string; actionLabel?: string; onAction?: () => void }) {
  return (
    <div role="alert" className="rounded-2xl border border-red-200 bg-red-50 p-5 text-red-800 dark:border-red-900 dark:bg-red-950/30 dark:text-red-200">
      <div className="flex items-start gap-3">
        <Icon name="warning" className="mt-0.5 h-5 w-5 shrink-0" />
        <div className="min-w-0">
          <h2 className="font-semibold">{title}</h2>
          {description && <p className="mt-1 text-sm opacity-80">{description}</p>}
          {actionLabel && onAction && (
            <button type="button" onClick={onAction} className="mt-3 rounded-xl border border-current px-3 py-1.5 text-sm font-semibold transition-colors hover:bg-red-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 dark:hover:bg-red-950">
              {actionLabel}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
