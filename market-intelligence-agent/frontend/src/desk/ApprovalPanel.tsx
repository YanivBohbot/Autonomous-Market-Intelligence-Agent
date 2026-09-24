import { useRef, useState } from "react";
import { EDITABLE_FIELDS, type ActionRequest, type Decision, type DecisionType, type PendingApproval } from "./approvals";

interface Props {
  approval: PendingApproval;
  onSubmit: (decisions: Decision[]) => void;
  onCancel: () => void;
}

const btn = "rounded border px-3 py-1 font-mono text-xs transition-colors disabled:opacity-40";

// One card per pending side-effect call; once every card is decided, the
// decisions go out together, in request order, exactly once.
export function ApprovalPanel({ approval, onSubmit, onCancel }: Props) {
  const [decisions, setDecisions] = useState<(Decision | undefined)[]>(() => approval.requests.map(() => undefined));
  const submitted = useRef(false);

  function decide(index: number, decision: Decision) {
    if (submitted.current) return;
    const next = [...decisions];
    next[index] = decision;
    setDecisions(next);
    if (next.every((d) => d !== undefined)) {
      submitted.current = true;
      onSubmit(next as Decision[]);
    }
  }

  if (approval.requests.length === 0) {
    return (
      <div className="rounded-xl border border-terminal-warn/40 bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
        <p className="mb-2">The agent paused with a request this console can't display.</p>
        <button
          type="button"
          className={`${btn} border-terminal-danger/50 text-terminal-danger`}
          onClick={() => {
            if (submitted.current) return;
            submitted.current = true;
            onCancel();
          }}
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {approval.requests.map((req, i) => (
        <RequestCard
          key={i}
          request={req}
          allowed={approval.allowed[i] ?? ["approve", "edit", "reject"]}
          decided={decisions[i]}
          onDecide={(d) => decide(i, d)}
        />
      ))}
    </div>
  );
}

function RequestCard({
  request,
  allowed,
  decided,
  onDecide,
}: {
  request: ActionRequest;
  allowed: DecisionType[];
  decided: Decision | undefined;
  onDecide: (d: Decision) => void;
}) {
  const fields = EDITABLE_FIELDS[request.name];
  const [editing, setEditing] = useState(false);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((fields ?? []).map((f) => [f, String(request.args[f] ?? "")])),
  );
  const can = (d: DecisionType) => allowed.includes(d);
  const locked = decided !== undefined;

  return (
    <div className="rounded-xl border border-terminal-warn/40 bg-terminal-panel p-3 font-mono text-xs text-terminal-text">
      <div className="mb-2 flex items-center justify-between">
        <span className="font-semibold text-terminal-warn">{request.name}</span>
        {locked && <span className="text-terminal-muted">{decided.type}</span>}
      </div>

      {fields ? (
        <div className="flex flex-col gap-1.5">
          {fields.map((f) => {
            const multiline = f === "body" || f === "content";
            const common = {
              id: `${request.name}-${f}`,
              "aria-label": f,
              value: values[f],
              readOnly: !editing || locked,
              onChange: (e: { target: { value: string } }) => setValues({ ...values, [f]: e.target.value }),
              className:
                "w-full rounded border border-terminal-border bg-terminal-bg px-2 py-1 text-terminal-text read-only:opacity-80",
            };
            return (
              <label key={f} className="flex flex-col gap-0.5">
                <span className="text-[10px] uppercase text-terminal-muted">{f}</span>
                {multiline ? <textarea rows={4} {...common} /> : <input {...common} />}
              </label>
            );
          })}
        </div>
      ) : (
        <pre className="overflow-x-auto rounded bg-terminal-bg p-2 text-[11px]">{JSON.stringify(request.args, null, 2)}</pre>
      )}

      {rejecting && !locked && (
        <label className="mt-2 flex flex-col gap-0.5">
          <span className="text-[10px] uppercase text-terminal-muted">reason (optional)</span>
          <input
            aria-label="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="rounded border border-terminal-border bg-terminal-bg px-2 py-1"
          />
        </label>
      )}

      {!locked && (
        <div className="mt-2 flex gap-2">
          {can("approve") && !editing && !rejecting && (
            <button
              type="button"
              className={`${btn} border-terminal-accent/50 text-terminal-accent`}
              onClick={() => onDecide({ type: "approve" })}
            >
              Approve
            </button>
          )}
          {can("edit") && fields && !editing && !rejecting && (
            <button type="button" className={`${btn} border-terminal-border text-terminal-text`} onClick={() => setEditing(true)}>
              Edit
            </button>
          )}
          {editing && (
            <button
              type="button"
              className={`${btn} border-terminal-accent/50 text-terminal-accent`}
              onClick={() => onDecide({ type: "edit", edited_action: { name: request.name, args: { ...request.args, ...values } } })}
            >
              Send edited
            </button>
          )}
          {can("reject") && !editing && !rejecting && (
            <button type="button" className={`${btn} border-terminal-danger/50 text-terminal-danger`} onClick={() => setRejecting(true)}>
              Reject
            </button>
          )}
          {rejecting && (
            <button
              type="button"
              className={`${btn} border-terminal-danger/50 text-terminal-danger`}
              onClick={() => onDecide(reason.trim() ? { type: "reject", message: reason.trim() } : { type: "reject" })}
            >
              Confirm reject
            </button>
          )}
        </div>
      )}
    </div>
  );
}
