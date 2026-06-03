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
    <div className="rounded-lg border border-terminal-warn/40 bg-terminal-warn/5 p-4">
      <div className="mb-1 font-mono text-xs uppercase tracking-wider text-terminal-warn">
        Awaiting approval
      </div>
      <p className="mb-3 font-mono text-sm text-terminal-text">{pending.action}</p>
      <div className="flex gap-2">
        <button
          disabled={busy}
          onClick={() => decide(true)}
          className="rounded bg-terminal-accent px-4 py-1.5 text-sm font-semibold text-terminal-bg disabled:opacity-50"
        >
          Approve
        </button>
        <button
          disabled={busy}
          onClick={() => decide(false)}
          className="rounded border border-terminal-danger px-4 py-1.5 text-sm font-semibold text-terminal-danger disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </div>
  );
}
