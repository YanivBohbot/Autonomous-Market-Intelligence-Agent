import { useRef, useState } from "react";
import { EDITABLE_FIELDS, type ActionRequest, type Decision, type DecisionType, type PendingApproval } from "./approvals";
import { EmailAttachmentSelector } from "./EmailAttachmentSelector";
import { Icon } from "../ui/Icon";
import { StatusBadge, type StatusTone } from "../ui/StatusBadge";
import { SurfaceCard } from "../ui/SurfaceCard";

interface Props {
  approval: PendingApproval;
  onSubmit: (decisions: Decision[]) => void;
  onCancel: () => void;
}

const btn = "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border px-4 py-2 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-40";
const primaryBtn = `${btn} border-emerald-600 bg-emerald-600 text-white shadow-sm hover:border-emerald-700 hover:bg-emerald-700`;
const secondaryBtn = `${btn} border-terminal-border bg-terminal-panel text-terminal-text hover:bg-[rgb(var(--surface-soft))]`;
const dangerBtn = `${btn} border-red-200 bg-terminal-panel text-terminal-danger hover:bg-red-50 dark:border-red-900 dark:hover:bg-red-950/30`;

const EMAIL_FIELD_LABELS: Record<string, string> = {
  recipient: "Recipient",
  subject: "Subject",
  body: "Message",
};

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
      <div className="rounded-xl border border-terminal-warn/40 bg-terminal-panel card-shadow p-3 font-mono text-xs text-terminal-text">
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
  const isEmail = request.name === "send_email";
  const startsEmpty = isEmail && ["subject", "body"].some((f) => !String(request.args[f] ?? "").trim());
  const [editing, setEditing] = useState(startsEmpty);
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState("");
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries((fields ?? []).map((f) => [f, String(request.args[f] ?? "")])),
  );
  const originalAttachment = request.name === "send_email" && typeof request.args.attachment_filename === "string"
    ? request.args.attachment_filename
    : "";
  const [attachment, setAttachment] = useState(originalAttachment);
  const editSnapshot = useRef({ values: { ...values }, attachment: originalAttachment });
  const can = (d: DecisionType) => allowed.includes(d);
  const emptyDraft = isEmail && ["subject", "body"].some((f) => !(values[f] ?? "").trim());
  const locked = decided !== undefined;

  function editedEmailArgs(includeFieldEdits: boolean) {
    return {
      ...request.args,
      ...(includeFieldEdits ? values : {}),
      attachment_filename: attachment || null,
    };
  }

  function resetEmailEdits() {
    setValues({ ...editSnapshot.current.values });
    setAttachment(editSnapshot.current.attachment);
    setEditing(false);
  }

  function startEmailEditing() {
    editSnapshot.current = { values: { ...values }, attachment };
    setEditing(true);
  }

  const decisionLabel = decided?.type === "reject"
    ? "Rejected"
    : decided?.type === "edit"
      ? "Approved with changes"
      : decided?.type === "approve"
        ? "Approved"
        : null;
  const statusTone: StatusTone = locked
    ? decided?.type === "reject" ? "danger" : "success"
    : rejecting ? "danger" : editing ? "info" : "warning";

  return (
    <SurfaceCard padding="none" className={isEmail ? "overflow-hidden border-blue-200 dark:border-blue-900" : "p-3 font-mono text-xs text-terminal-text"}>
      {isEmail ? (
        <div className="flex flex-col gap-4 border-b border-terminal-border bg-gradient-to-r from-blue-50 via-terminal-panel to-emerald-50 px-5 py-5 sm:flex-row sm:items-start sm:justify-between dark:from-blue-950/30 dark:via-terminal-panel dark:to-emerald-950/20">
          <div className="flex min-w-0 items-start gap-3.5">
            <span className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-blue-600 text-white shadow-sm" aria-hidden="true">
              <Icon name="mail" className="h-5 w-5" />
            </span>
            <div className="min-w-0">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700 dark:text-blue-300">Email delivery</p>
              <h3 className="mt-1 text-lg font-semibold tracking-tight text-terminal-text">Review email before sending</h3>
              <p className="mt-1 text-sm text-terminal-muted">Check the recipient, message, and selected report before delivery.</p>
            </div>
          </div>
          <StatusBadge tone={statusTone}>{decisionLabel ?? (rejecting ? "Rejection review" : editing ? "Editing draft" : "Approval required")}</StatusBadge>
        </div>
      ) : (
        <div className="mb-2 flex items-center justify-between">
          <span className="font-semibold text-terminal-warn">{request.name}</span>
          {locked && <span className="text-terminal-muted">{decided.type}</span>}
        </div>
      )}

      {fields ? (
        <div className={isEmail ? "grid gap-4 p-5" : "flex flex-col gap-1.5"}>
          {fields.map((f) => {
            const multiline = f === "body" || f === "content";
            const fieldLabel = isEmail ? EMAIL_FIELD_LABELS[f] ?? f : f;
            const common = {
              id: `${request.name}-${f}`,
              "aria-label": fieldLabel,
              value: values[f],
              autoFocus: startsEmpty && f === "subject",
              readOnly: !editing || locked,
              onChange: (e: { target: { value: string } }) => setValues({ ...values, [f]: e.target.value }),
              className: isEmail
                ? "w-full rounded-xl border border-terminal-border bg-terminal-panel px-3.5 py-2.5 text-sm text-terminal-text shadow-sm outline-none transition placeholder:text-terminal-muted focus:border-blue-500 focus:ring-2 focus:ring-blue-500/15 read-only:bg-[rgb(var(--surface-soft))] read-only:shadow-none"
                : "w-full rounded border border-terminal-border bg-terminal-bg px-2 py-1 text-terminal-text read-only:opacity-80",
            };
            return (
              <label key={f} className={isEmail ? "flex flex-col gap-1.5" : "flex flex-col gap-0.5"}>
                <span className={isEmail ? "text-xs font-semibold text-terminal-muted" : "text-[10px] uppercase text-terminal-muted"}>{fieldLabel}</span>
                {multiline ? <textarea rows={isEmail ? 5 : 4} {...common} /> : <input type={isEmail && f === "recipient" ? "email" : "text"} {...common} />}
              </label>
            );
          })}
        </div>
      ) : (
        <pre className="overflow-x-auto rounded bg-terminal-bg p-2 text-[11px]">{JSON.stringify(request.args, null, 2)}</pre>
      )}

      {request.name === "send_email" && (
        <div className="px-5 pb-5">
          <EmailAttachmentSelector
            value={attachment}
            disabled={locked || !can("edit")}
            onChange={setAttachment}
          />
        </div>
      )}

      {rejecting && !locked && (
        <label className={isEmail ? "mx-5 mb-5 flex flex-col gap-1.5 rounded-xl border border-red-200 bg-red-50 p-4 dark:border-red-900 dark:bg-red-950/30" : "mt-2 flex flex-col gap-0.5"}>
          <span className={isEmail ? "text-xs font-semibold text-red-700 dark:text-red-300" : "text-[10px] uppercase text-terminal-muted"}>Reason (optional)</span>
          <input
            aria-label="reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className={isEmail ? "rounded-xl border border-red-200 bg-terminal-panel px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-red-500/20 dark:border-red-900" : "rounded border border-terminal-border bg-terminal-bg px-2 py-1"}
            placeholder={isEmail ? "Add context for the rejection" : undefined}
          />
        </label>
      )}

      {!locked && isEmail && (
        <div className="border-t border-terminal-border bg-[rgb(var(--surface-soft))] px-5 py-4">
          <p className="flex items-center gap-2 text-xs text-terminal-muted">
            <Icon name="shield" className="h-4 w-4 text-emerald-600" />
            Nothing is sent until you approve.
          </p>
          {emptyDraft && (
            <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-300">
              Add a subject and a message to send this email.
            </p>
          )}
          <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              {can("reject") && !rejecting && (
                <button
                  type="button"
                  className={dangerBtn}
                  onClick={() => {
                    if (editing) resetEmailEdits();
                    setRejecting(true);
                  }}
                >
                  <Icon name="close" className="h-4 w-4" />
                  Reject
                </button>
              )}
            </div>
            <div className="flex flex-col-reverse gap-2 sm:flex-row">
              {editing && (
                <button type="button" className={secondaryBtn} onClick={resetEmailEdits}>
                  Cancel changes
                </button>
              )}
              {rejecting && (
                <button type="button" className={secondaryBtn} onClick={() => { setRejecting(false); setReason(""); }}>
                  Cancel rejection
                </button>
              )}
              {can("edit") && !editing && !rejecting && (
                <button type="button" className={secondaryBtn} onClick={startEmailEditing}>
                  <Icon name="edit" className="h-4 w-4" />
                  Edit email
                </button>
              )}
              {editing && (
                <button
                  type="button"
                  className={primaryBtn}
                  disabled={emptyDraft}
                  onClick={() => onDecide({
                    type: "edit",
                    edited_action: { name: request.name, args: editedEmailArgs(true) },
                  })}
                >
                  <Icon name="send" className="h-4 w-4" />
                  Approve changes &amp; send
                </button>
              )}
              {rejecting && (
                <button
                  type="button"
                  className={`${btn} border-red-600 bg-red-600 text-white hover:bg-red-700`}
                  onClick={() => onDecide(reason.trim() ? { type: "reject", message: reason.trim() } : { type: "reject" })}
                >
                  Confirm reject
                </button>
              )}
              {can("approve") && !editing && !rejecting && (
                <button
                  type="button"
                  className={primaryBtn}
                  disabled={emptyDraft}
                  onClick={() => {
                    if (attachment !== originalAttachment) {
                      onDecide({
                        type: "edit",
                        edited_action: { name: request.name, args: editedEmailArgs(false) },
                      });
                      return;
                    }
                    onDecide({ type: "approve" });
                  }}
                >
                  <Icon name="send" className="h-4 w-4" />
                  Approve &amp; send
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {!locked && !isEmail && (
        <div className="mt-2 flex gap-2">
          {can("approve") && !editing && !rejecting && (
            <button
              type="button"
              className={`${btn} border-terminal-accent/50 text-terminal-accent`}
              onClick={() => {
                if (request.name === "send_email" && attachment !== originalAttachment) {
                  onDecide({
                    type: "edit",
                    edited_action: { name: request.name, args: editedEmailArgs(false) },
                  });
                  return;
                }
                onDecide({ type: "approve" });
              }}
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
              onClick={() => onDecide({
                type: "edit",
                edited_action: {
                  name: request.name,
                  args: request.name === "send_email"
                    ? editedEmailArgs(true)
                    : { ...request.args, ...values },
                },
              })}
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
    </SurfaceCard>
  );
}
