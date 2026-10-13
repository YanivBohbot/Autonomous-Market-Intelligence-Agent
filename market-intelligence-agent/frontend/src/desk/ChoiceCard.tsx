import { useState } from "react";

export interface ChoiceRequest {
  question: string;
  options: { id: string; label: string }[];
  multi: boolean;
  allow_other: boolean;
}
export type ChoiceAnswer = { selected: string[]; other: string | null; cancelled?: true };

function isRecord(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

// ask_user_choice's interrupt payload, surfaced by ag-ui-langgraph at
// interrupt.metadata.langgraph.raw (same place readApproval looks).
export function readChoice(interrupt: unknown): ChoiceRequest | null {
  const raw = isRecord(interrupt) && isRecord(interrupt.metadata) && isRecord(interrupt.metadata.langgraph)
    ? interrupt.metadata.langgraph.raw
    : undefined;
  if (!isRecord(raw) || raw.type !== "user_choice" || !Array.isArray(raw.options)) return null;
  return {
    question: String(raw.question ?? ""),
    options: raw.options as ChoiceRequest["options"],
    multi: raw.multi === true,
    allow_other: raw.allow_other === true,
  };
}

export function ChoiceCard({ request, onSubmit }: { request: ChoiceRequest; onSubmit: (a: ChoiceAnswer) => void }) {
  const [ticked, setTicked] = useState<string[]>([]);
  const [other, setOther] = useState("");
  const otherValue = request.allow_other && other.trim() ? other.trim() : null;
  return (
    <div className="rounded-xl border border-terminal-accent/40 bg-terminal-panel card-shadow p-3 text-sm text-terminal-text">
      <div className="mb-2 font-semibold">{request.question}</div>
      <div className="flex flex-wrap gap-2">
        {request.options.map((o) =>
          request.multi ? (
            <label key={o.id} className="flex items-center gap-1.5 rounded-lg border border-terminal-border px-2 py-1">
              <input
                type="checkbox"
                aria-label={o.label}
                checked={ticked.includes(o.id)}
                onChange={() => setTicked((t) => (t.includes(o.id) ? t.filter((x) => x !== o.id) : [...t, o.id]))}
              />
              {o.label}
            </label>
          ) : (
            <button
              key={o.id}
              type="button"
              onClick={() => onSubmit({ selected: [o.id], other: null })}
              className="rounded-lg border border-terminal-border px-3 py-1 hover:border-terminal-accent"
            >
              {o.label}
            </button>
          ),
        )}
      </div>
      {request.allow_other && (
        <input
          aria-label="Other"
          placeholder="Other…"
          value={other}
          onChange={(e) => setOther(e.target.value)}
          className="mt-2 w-full rounded-lg border border-terminal-border bg-terminal-bg px-2 py-1"
        />
      )}
      <div className="mt-2 flex gap-2">
      {(request.multi || request.allow_other) && (
        <button
          type="button"
          disabled={ticked.length === 0 && !otherValue}
          onClick={() => onSubmit({ selected: ticked, other: otherValue })}
          className="rounded-lg bg-terminal-accent px-3 py-1 font-semibold text-terminal-bg disabled:opacity-40"
        >
          Confirm
        </button>
      )}
        {/* Always offered: a pending choice blocks the thread until it is answered. */}
        <button
          type="button"
          onClick={() => onSubmit({ selected: [], other: null, cancelled: true })}
          className="rounded-lg border border-terminal-border px-3 py-1 text-terminal-muted hover:text-terminal-text"
        >
          None of these
        </button>
      </div>
    </div>
  );
}
