import { useState } from "react";
import { postApprove } from "../lib/api";
import type { PendingAction } from "../lib/types";

interface Props {
  threadId: string;
  pending: PendingAction;
  onResolved: (responseText: string, stillPending: PendingAction | null) => void;
}

export function ApprovalCard({ threadId, pending, onResolved }: Props) {
  const [busy, setBusy] = useState(false);

  async function decide(approved: boolean) {
    setBusy(true);
    try {
      const res = await postApprove(threadId, approved);
      const stillPending: PendingAction | null =
        res.status === "interrupted"
          ? { action: res.response, nextStep: res.next_step ?? "" }
          : null;
      onResolved(res.response, stillPending);
    } catch (err) {
      onResolved(`Approval failed: ${(err as Error).message}`, null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="animate-fade-in-up rounded-xl border border-terminal-warn/30 bg-gradient-to-b from-terminal-warn/5 to-transparent shadow-glow-amber">
      {/* Top bar */}
      <div className="flex items-center gap-2 rounded-t-xl border-b border-terminal-warn/20 bg-terminal-warn/8 px-4 py-2">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-terminal-warn" />
        <span className="font-mono text-[10px] font-semibold uppercase tracking-widest text-terminal-warn">
          Human approval required
        </span>
      </div>

      {/* Action payload */}
      <div className="px-4 py-3">
        <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-terminal-muted">
          Requested action
        </div>
        <p className="rounded-lg border border-terminal-border bg-terminal-bg px-3 py-2 font-mono text-sm text-terminal-text">
          {pending.action}
        </p>
      </div>

      {/* Decision buttons */}
      <div className="flex gap-2 px-4 pb-3">
        <button
          disabled={busy}
          onClick={() => decide(true)}
          className="flex items-center gap-1.5 rounded-lg bg-terminal-accent px-4 py-2 font-mono text-sm font-semibold text-terminal-bg shadow-glow-green transition-all hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy ? (
            <span className="animate-pulse">…</span>
          ) : (
            <>
              <span>✓</span> Approve
            </>
          )}
        </button>
        <button
          disabled={busy}
          onClick={() => decide(false)}
          className="flex items-center gap-1.5 rounded-lg border border-terminal-danger/60 bg-terminal-danger/5 px-4 py-2 font-mono text-sm font-semibold text-terminal-danger transition-all hover:bg-terminal-danger/10 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span>✗</span> Reject
        </button>
      </div>
    </div>
  );
}
