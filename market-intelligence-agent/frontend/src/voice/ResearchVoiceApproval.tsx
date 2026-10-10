import { useRef, useState } from "react";
import { ApprovalPanel } from "../desk/ApprovalPanel";
import { readApproval, type Decision } from "../desk/approvals";
import { useResearchVoiceContext } from "./ResearchVoiceContext";
import type { VoiceDecision, VoicePendingApproval } from "./types";

export function ResearchVoiceApproval({
  pending,
}: {
  pending: VoicePendingApproval;
}) {
  const voice = useResearchVoiceContext();
  const submitted = useRef(false);
  const [error, setError] = useState<string | null>(null);
  const approval = readApproval({
    metadata: { langgraph: { raw: pending } },
  });

  if (!voice) return null;

  async function submit(decisions: Decision[]) {
    if (submitted.current || !voice) return;
    submitted.current = true;
    setError(null);
    try {
      await voice.submitDecision(
        pending.interrupt_id,
        decisions as VoiceDecision[],
      );
    } catch (decisionError) {
      submitted.current = false;
      setError(
        decisionError instanceof Error
          ? decisionError.message
          : "Voice decision failed",
      );
    }
  }

  return (
    <div className="space-y-2">
      <ApprovalPanel
        approval={approval}
        onSubmit={(decisions) => void submit(decisions)}
        onCancel={() => void submit([{ type: "reject" }])}
      />
      {error && (
        <p role="alert" className="rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900 dark:bg-red-950/30 dark:text-red-300">
          {error}
        </p>
      )}
    </div>
  );
}
