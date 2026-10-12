import type { DisplayPayload } from "./types";

type FileList = Extract<DisplayPayload, { type: "file_list" }>;
type IconKind = "folder" | "image" | "sheet" | "text" | "file";

function iconKind(name: string): IconKind {
  const ext = name.toLowerCase().split(".").pop() ?? "";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg"].includes(ext)) return "image";
  if (["xlsx", "xls", "csv"].includes(ext)) return "sheet";
  if (["txt", "md", "json", "yml", "yaml", "log"].includes(ext)) return "text";
  return "file";
}

function Icon({ kind }: { kind: IconKind }) {
  const common = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.5, className: "shrink-0" };
  switch (kind) {
    case "folder":
      return <svg {...common} className="shrink-0 text-terminal-accent"><path d="M3 6a1 1 0 0 1 1-1h5l2 2h9a1 1 0 0 1 1 1v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6Z" /></svg>;
    case "image":
      return <svg {...common}><rect x="3" y="4" width="18" height="16" rx="1" /><circle cx="9" cy="10" r="1.5" /><path d="m4 18 5-5 4 4 3-3 4 4" /></svg>;
    case "sheet":
      return <svg {...common}><rect x="4" y="3" width="16" height="18" rx="1" /><path d="M4 9h16M4 15h16M10 3v18" /></svg>;
    case "text":
      return <svg {...common}><path d="M6 2h9l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z" /><path d="M14 2v5h5M8 13h8M8 17h6" /></svg>;
    default:
      return <svg {...common}><path d="M6 2h9l5 5v15a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1Z" /><path d="M14 2v5h5" /></svg>;
  }
}

function plural(n: number, word: string): string {
  return `${n} ${word}${n === 1 ? "" : "s"}`;
}

export function FileListCard({ display }: { display: FileList }) {
  const title = display.path === "." ? "workspace" : `workspace/${display.path}`;
  return (
    <div className="rounded-xl border border-terminal-border bg-terminal-panel card-shadow p-3">
      <div className="mb-2 flex items-center justify-between gap-3">
        <span className="truncate font-mono text-xs font-semibold text-terminal-text">{title}</span>
        <span className="shrink-0 font-mono text-[11px] text-terminal-muted">
          {plural(display.dirs.length, "folder")} · {plural(display.files.length, "file")}
        </span>
      </div>
      <ul className="flex flex-col divide-y divide-terminal-border/60">
        {display.dirs.map((dir) => (
          <li key={`d:${dir}`} className="flex items-center gap-2.5 py-1.5 text-terminal-text">
            <Icon kind="folder" />
            <span className="truncate font-mono text-xs">{dir}</span>
          </li>
        ))}
        {display.files.map((file) => {
          const kind = iconKind(file.name);
          return (
            <li key={`f:${file.name}`} className="flex items-center gap-2.5 py-1.5 text-terminal-muted">
              <Icon kind={kind} />
              {file.url ? (
                <a
                  href={file.url}
                  {...(kind === "image" ? { target: "_blank", rel: "noreferrer" } : { download: true })}
                  className="truncate font-mono text-xs text-terminal-accent hover:underline"
                >
                  {file.name}
                </a>
              ) : (
                <span className="truncate font-mono text-xs text-terminal-text">{file.name}</span>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
