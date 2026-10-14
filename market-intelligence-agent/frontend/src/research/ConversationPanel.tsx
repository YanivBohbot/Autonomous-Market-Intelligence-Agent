import { useCallback, useEffect, useState } from "react";
import { deleteConversation, listConversations, renameConversation, type Conversation } from "./conversationsApi";
import { relativeTime } from "./relativeTime";

type Props = {
  activeId: string;
  refreshKey: number;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDeleted: (id: string) => void;
};

export function ConversationPanel({ activeId, refreshKey, onSelect, onNew, onDeleted }: Props) {
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<Conversation[] | null>(null);
  const [error, setError] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  const load = useCallback(async (q: string) => {
    try {
      setItems(await listConversations(q));
      setError(false);
    } catch {
      setError(true);
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
    const row = await renameConversation(id, title);
    setItems((cur) => cur?.map((c) => (c.id === id ? { ...c, title: row.title } : c)) ?? cur);
  }

  async function confirmDelete(id: string) {
    setConfirming(null);
    await deleteConversation(id);
    setItems((cur) => cur?.filter((c) => c.id !== id) ?? cur);
    onDeleted(id);
  }

  return (
    <aside aria-label="Conversations" className="flex w-64 shrink-0 flex-col border-r border-terminal-border bg-terminal-panel">
      <div className="space-y-2 border-b border-terminal-border p-3">
        <button type="button" onClick={onNew} className="w-full rounded-xl border border-terminal-border px-3 py-2 text-xs font-semibold text-terminal-muted hover:border-brand-blue/50 hover:text-brand-blue">
          + New conversation
        </button>
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
