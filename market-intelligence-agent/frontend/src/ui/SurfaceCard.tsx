import type { PropsWithChildren } from "react";

export type SurfaceTone = "default" | "soft" | "gradient";

const TONE_CLASSES: Record<SurfaceTone, string> = {
  default: "bg-terminal-panel",
  soft: "bg-[rgb(var(--surface-soft))]",
  gradient: "bg-gradient-to-br from-blue-50 via-terminal-panel to-emerald-50 dark:from-blue-950/30 dark:via-terminal-panel dark:to-emerald-950/20",
};

const PADDING_CLASSES = { none: "", sm: "p-3", md: "p-4", lg: "p-5 md:p-6" } as const;

export function SurfaceCard({
  children,
  className = "",
  tone = "default",
  padding = "md",
}: PropsWithChildren<{ className?: string; tone?: SurfaceTone; padding?: keyof typeof PADDING_CLASSES }>) {
  return (
    <section
      data-tone={tone}
      className={`rounded-2xl border border-terminal-border card-shadow ${TONE_CLASSES[tone]} ${PADDING_CLASSES[padding]} ${className}`}
    >
      {children}
    </section>
  );
}
