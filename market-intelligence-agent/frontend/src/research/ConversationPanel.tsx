import { useCallback, useEffect, useRef, useState } from "react";
import { deleteConversation, listConversations, renameConversation, type Conversation } from "./conversationsApi";
import { relativeTime } from "./relativeTime";

const COLLAPSED_KEY = "research.conversations.collapsed";

// Per-viewer convenience only: storage can be unavailable (private mode).
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean) {
  try {
    localStorage.setItem(COLLAPSED_KEY, value ? "1" : "0");
  } catch {
    // ignore
  }
}

type Props = {
  activeId: string;
  refreshKey: number;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDeleted: (id: string) => void;
};

const railButton =
  "grid h-8 w-8 shrink-0 place-items-center rounded-lg border border-terminal-border text-sm text-terminal-muted hover:border-brand-blue/50 hover:text-brand-blue focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-blue";

export function ConversationPanel({ activeId, refreshKey, onSelect, onNew, onDeleted }: Props) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Conversation[] | null>(null);
  const [error, setError] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [collapsed, setCollapsed] = useState(readCollapsed);

  function toggle(next: boolean) {
    setCollapsed(next);
    writeCollapsed(next);
  }

  const [actionError, setActionError] = useState<string | null>(null);
  // Only the latest list request may update the panel: a slow semantic
  // search must not overwrite a newer plain list (or bring back a deleted row).
  const latestRequest = useRef(0);

  const load = useCallback(async (q: string) => {
    const id = ++latestRequest.current;
    try {
      const rows = await listConversations(q);
      if (id !== latestRequest.current) return;
      setItems(rows);
      setError(false);
    } catch {
      if (id === latestRequest.current) setError(true);
    }
  }, []);

  useEffect(() => {
    const t = setTimeout(() => void load(query), query ? 300 : 0);
    return () => clearTimeout(t);
  }, [load, query, refreshKey, attempt]);

  async function commitRename(id: string) {
    const title = draft.trim();
    setEditing(null);
    if (!title) return;
    try {
      const row = await renameConversation(id, title);
      setActionError(null);
      setItems((cur) => cur?.map((c) => (c.id === id ? { ...c, title: row.title } : c)) ?? cur);
    } catch {
      setActionError("Couldn't rename this conversation");
    }
  }

  async function confirmDelete(id: string) {
    setConfirming(null);
    try {
      await deleteConversation(id);
    } catch {
      // 409 while a turn is running in it, or the backend is down.
      setActionError("Couldn't delete this conversation");
      return;
    }
    setActionError(null);
    latestRequest.current += 1; // drop any in-flight list that still has it
    setItems((cur) => cur?.filter((c) => c.id !== id) ?? cur);
    onDeleted(id);
  }

  if (collapsed) {
    return (
      <aside aria-label="Conversations" className="flex w-11 shrink-0 flex-col items-center gap-2 border-r border-terminal-border bg-terminal-panel py-3">
        <button type="button" aria-label="Show conversations" title="Show conversations" onClick={() => toggle(false)} className={railButton}>
          <span aria-hidden="true">»</span>
        </button>
        <button type="button" aria-label="New conversation" title="New conversation" onClick={onNew} className={railButton}>
          <span aria-hidden="true">+</span>
        </button>
      </aside>
    );
  }

  return (
    <aside aria-label="Conversations" className="flex w-64 shrink-0 flex-col border-r border-terminal-border bg-terminal-panel">
      <div className="space-y-2 border-b border-terminal-border p-3">
        <div className="flex gap-2">
          <button type="button" onClick={onNew} className="flex-1 rounded-xl border border-terminal-border px-3 py-2 text-xs font-semibold text-terminal-muted hover:border-brand-blue/50 hover:text-brand-blue">
            + New conversation
          </button>
          <button type="button" aria-label="Hide conversations" title="Hide conversations" onClick={() => toggle(true)} className={railButton}>
            <span aria-hidden="true">«</span>
          </button>
        </div>
        <input
          type="search"
          aria-label="Search conversations"
          placeholder="Search conversations…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-lg border border-terminal-border bg-terminal-bg px-2 py-1.5 text-xs"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {error && (
          <div className="p-2 text-xs text-terminal-muted">
            <p>Couldn't load conversations</p>
            <button type="button" onClick={() => setAttempt((n) => n + 1)} className="mt-1 font-semibold text-brand-blue">Retry</button>
          </div>
        )}
        {actionError && (
          <p role="alert" className="mb-2 rounded-lg border border-terminal-warn/40 bg-terminal-warn/10 px-2 py-1.5 text-[11px] text-terminal-warn">
            {actionError}
          </p>
        )}
        {!error && items?.length === 0 && <p className="p-2 text-xs text-terminal-muted">No conversations yet</p>}
        <ul className="space-y-1">
          {items?.map((c) => (
            <li key={c.id} className="group relative">
              {editing === c.id ? (
                <input
                  aria-label="Conversation title"
                  autoFocus
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void commitRename(c.id);
                    if (e.key === "Escape") setEditing(null);
                  }}
                  onBlur={() => void commitRename(c.id)}
                  className="w-full rounded-lg border border-brand-blue px-2 py-1.5 text-xs"
                />
              ) : (
                <button
                  type="button"
                  aria-current={c.id === activeId ? "true" : undefined}
                  onClick={() => onSelect(c.id)}
                  className={`w-full rounded-lg px-2 py-1.5 text-left text-xs ${c.id === activeId ? "bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300" : "text-terminal-text hover:bg-surface-soft"}`}
                >
                  <span className="block truncate font-medium">{c.title}</span>
                  <span className="block text-[10px] text-terminal-muted">{relativeTime(c.updated_at)}</span>
                </button>
              )}
              {editing !== c.id && (
                <div className="absolute right-1 top-1 hidden gap-1 group-hover:flex group-focus-within:flex">
                  <button type="button" onClick={() => { setDraft(c.title); setEditing(c.id); }} className="rounded px-1 text-[10px] text-terminal-muted hover:text-terminal-text">Rename</button>
                  <button type="button" onClick={() => setConfirming(c.id)} className="rounded px-1 text-[10px] text-terminal-muted hover:text-terminal-warn">Delete</button>
                </div>
              )}
              {confirming === c.id && (
                <div role="alertdialog" className="mt-1 rounded-lg border border-terminal-warn/40 bg-terminal-warn/10 p-2 text-[11px]">
                  <p>Delete this conversation? This cannot be undone.</p>
                  <div className="mt-1 flex gap-2">
                    <button type="button" aria-label="Confirm delete" onClick={() => void confirmDelete(c.id)} className="font-semibold text-terminal-warn">Delete</button>
                    <button type="button" onClick={() => setConfirming(null)} className="text-terminal-muted">Cancel</button>
                  </div>
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>
    </aside>
  );
}
