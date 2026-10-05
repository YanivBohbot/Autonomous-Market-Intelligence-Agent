import type { ReactNode } from "react";

export type IconName =
  | "briefing"
  | "clients"
  | "research"
  | "reports"
  | "data"
  | "menu"
  | "activity"
  | "profile"
  | "theme"
  | "settings"
  | "close"
  | "document"
  | "upload"
  | "check"
  | "warning";

const PATHS: Record<IconName, ReactNode> = {
  briefing: <path d="M4 19V9m5 10V5m5 14v-7m5 7V3" />,
  clients: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
  research: <><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4M8 11h6M11 8v6" /></>,
  reports: <><path d="M6 2h9l4 4v16H6z" /><path d="M14 2v5h5M9 13h6M9 17h6" /></>,
  data: <><ellipse cx="12" cy="5" rx="8" ry="3" /><path d="M4 5v6c0 1.66 3.58 3 8 3s8-1.34 8-3V5M4 11v6c0 1.66 3.58 3 8 3s8-1.34 8-3v-6" /></>,
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  activity: <path d="M3 12h4l2-7 4 14 2-7h6" />,
  profile: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></>,
  theme: <path d="M20.5 14.5A8 8 0 0 1 9.5 3.5 8.5 8.5 0 1 0 20.5 14.5Z" />,
  settings: <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1V21h-4v-.09A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1-.4H3v-4h.09A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1V3h4v.09A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.13.37.34.7.6 1 .28.26.63.4 1 .4h.09v4H21a1.7 1.7 0 0 0-1.6.6Z" /></>,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  document: <><path d="M6 2h9l4 4v16H6z" /><path d="M14 2v5h5" /></>,
  upload: <path d="M12 16V4m0 0L7 9m5-5 5 5M5 20h14" />,
  check: <path d="m5 12 4 4L19 6" />,
  warning: <><path d="M12 3 2.7 19h18.6L12 3Z" /><path d="M12 9v4m0 3h.01" /></>,
};

export function Icon({ name, className = "h-5 w-5", title }: { name: IconName; className?: string; title?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      {title && <title>{title}</title>}
      {PATHS[name]}
    </svg>
  );
}
