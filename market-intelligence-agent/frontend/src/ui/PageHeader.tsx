import type { ReactNode } from "react";

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
  children,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <header className="rounded-3xl border border-blue-100 bg-gradient-to-br from-blue-50 via-white to-emerald-50 p-5 shadow-sm dark:border-terminal-border dark:from-blue-950/40 dark:via-terminal-panel dark:to-emerald-950/30 md:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          {eyebrow && <p className="text-xs font-bold uppercase tracking-[0.2em] text-blue-600 dark:text-blue-300">{eyebrow}</p>}
          <h1 className="mt-1.5 text-2xl font-semibold tracking-tight text-terminal-text md:text-3xl">{title}</h1>
          {description && <p className="mt-2 max-w-3xl text-sm leading-relaxed text-terminal-muted">{description}</p>}
        </div>
        {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
      </div>
      {children && <div className="mt-5">{children}</div>}
    </header>
  );
}
