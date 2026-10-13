import { useInterrupt } from "@copilotkit/react-core/v2";
import { useEffect, type ReactNode } from "react";
import { MARKET_DESK_AGENT_ID } from "./constants";
import { ApprovalPanel } from "./ApprovalPanel";
import { ChoiceCard, readChoice } from "./ChoiceCard";
import { readApproval } from "./approvals";

// Renders HITL approval cards (resume: {decisions: [...]}) and ask_user_choice
// choice cards (resume: {selected, other}) inside CopilotChat.
function PendingInterruptMarker({
  children,
  onPendingChange,
}: {
  children: ReactNode;
  onPendingChange?: (pending: boolean) => void;
}) {
  useEffect(() => {
    onPendingChange?.(true);
    return () => onPendingChange?.(false);
  }, [onPendingChange]);

  return <>{children}</>;
}

export function useDeskInterrupt(
  onPendingChange?: (pending: boolean) => void,
): void {
  useInterrupt({
    agentId: MARKET_DESK_AGENT_ID,
    render: ({ interrupt, resolve, cancel }) => {
      // ask_user_choice interrupts get a choice card; everything else is a
      // HumanInTheLoopMiddleware approval.
      const choice = readChoice(interrupt);
      return (
        <PendingInterruptMarker onPendingChange={onPendingChange}>
          {choice ? (
            <ChoiceCard request={choice} onSubmit={(answer) => void resolve(answer)} />
          ) : (
            <ApprovalPanel
              approval={readApproval(interrupt)}
              onSubmit={(decisions) => void resolve({ decisions })}
              onCancel={() => void cancel()}
            />
          )}
        </PendingInterruptMarker>
      );
    },
  });
}
