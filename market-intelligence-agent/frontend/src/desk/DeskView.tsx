import { useMemo } from "react";
import { CopilotChat, CopilotKitProvider, HttpAgent, useConfigureSuggestions } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";
import { MARKET_DESK_AGENT_ID, MARKET_DESK_URL } from "./constants";
import { DeskActivityRail } from "./DeskActivityRail";
import { useDeskInterrupt } from "./useDeskInterrupt";
import { useToolDisplay } from "./displays/useToolDisplay";
import { uploadToWorkspace } from "../lib/api";

// Market Desk: CopilotKit v2 talking AG-UI straight to FastAPI (no runtime).
// Remounted per thread by App (key={threadId}), so New session starts clean.
export function DeskView({ threadId }: { threadId: string }) {
  const agent = useMemo(() => new HttpAgent({ url: MARKET_DESK_URL }), []);
  return (
    <CopilotKitProvider
      agentId={MARKET_DESK_AGENT_ID}
      agents__unsafe_dev_only={{ [MARKET_DESK_AGENT_ID]: agent }}
      // The checkpointer already holds the thread: send only the new message.
      // Re-sending the whole list would re-add messages summarization removed.
      messageFilter={(messages) => messages.slice(-1)}
      showDevConsole={false}
      enableInspector={false}
    >
      <DeskBody threadId={threadId} />
    </CopilotKitProvider>
  );
}

function DeskBody({ threadId }: { threadId: string }) {
  useDeskInterrupt();
  useToolDisplay();
  useConfigureSuggestions({
    suggestions: [
      { title: "Portfolio value", message: "What is the total value of a client's portfolio?" },
      { title: "Stock price", message: "What is AAPL trading at?" },
      { title: "Concentration risk", message: "Are any clients over-concentrated in one stock?" },
    ],
  }, []);
  return (
    <div className="flex min-h-0 flex-1">
      <main className="flex min-w-0 flex-1 flex-col">
        <CopilotChat
          agentId={MARKET_DESK_AGENT_ID}
          threadId={threadId}
          className="h-full"
          attachments={{
            enabled: true,
            maxSize: 20 * 1024 * 1024,
            onUpload: async (file) => {
              const { path } = await uploadToWorkspace(file);
              return { type: "url", value: path, metadata: { filename: file.name } };
            },
          }}
        />
      </main>
      <DeskActivityRail />
    </div>
  );
}
