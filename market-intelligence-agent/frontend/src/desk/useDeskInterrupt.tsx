import { useInterrupt } from "@copilotkit/react-core/v2";
import { MARKET_DESK_AGENT_ID } from "./constants";
import { ApprovalPanel } from "./ApprovalPanel";
import { readApproval } from "./approvals";

// Renders HITL approval cards inside CopilotChat and resumes the graph with
// HumanInTheLoopMiddleware's {decisions: [...]} payload.
export function useDeskInterrupt(): void {
  useInterrupt({
    agentId: MARKET_DESK_AGENT_ID,
    render: ({ interrupt, resolve, cancel }) => (
      <ApprovalPanel
        approval={readApproval(interrupt)}
        onSubmit={(decisions) => void resolve({ decisions })}
        onCancel={() => void cancel()}
      />
    ),
  });
}
