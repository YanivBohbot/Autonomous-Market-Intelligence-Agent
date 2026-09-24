import { useMemo } from "react";
import { CopilotChat, CopilotKitProvider, HttpAgent } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { MARKET_DESK_AGENT_ID, MARKET_DESK_URL } from "./constants";
import { DeskActivityRail } from "./DeskActivityRail";
import { useDeskInterrupt } from "./useDeskInterrupt";

// Market Desk: CopilotKit v2 talking AG-UI straight to FastAPI (no runtime).
// Remounted per thread by App (key={threadId}), so New session starts clean.
export function DeskView({ threadId }: { threadId: string }) {
  const agent = useMemo(() => new HttpAgent({ url: MARKET_DESK_URL }), []);
  return (
    <CopilotKitProvider
      agentId={MARKET_DESK_AGENT_ID}
      agents__unsafe_dev_only={{ [MARKET_DESK_AGENT_ID]: agent }}
      showDevConsole={false}
    >
      <DeskBody threadId={threadId} />
    </CopilotKitProvider>
  );
}

function DeskBody({ threadId }: { threadId: string }) {
  useDeskInterrupt();
  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <CopilotChat agentId={MARKET_DESK_AGENT_ID} threadId={threadId} className="h-full" />
      </main>
      <DeskActivityRail />
    </div>
  );
}
