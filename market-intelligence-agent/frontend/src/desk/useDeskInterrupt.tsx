import { useInterrupt } from "@copilotkit/react-core/v2";
import { useEffect, type ReactNode } from "react";
import { MARKET_DESK_AGENT_ID } from "./constants";
import { ApprovalPanel } from "./ApprovalPanel";
import { readApproval } from "./approvals";

// Renders HITL approval cards inside CopilotChat and resumes the graph with
// HumanInTheLoopMiddleware's {decisions: [...]} payload.
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
    render: ({ interrupt, resolve, cancel }) => (
      <PendingInterruptMarker onPendingChange={onPendingChange}>
        <ApprovalPanel
          approval={readApproval(interrupt)}
          onSubmit={(decisions) => void resolve({ decisions })}
          onCancel={() => void cancel()}
        />
      </PendingInterruptMarker>
    ),
  });
}
