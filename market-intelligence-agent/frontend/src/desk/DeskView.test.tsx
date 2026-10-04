import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

const chatProps: Record<string, unknown>[] = [];
const createdAgents: { setMessages: ReturnType<typeof vi.fn> }[] = [];
vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  CopilotChat: (props: Record<string, unknown>) => {
    chatProps.push(props);
    return null;
  },
  HttpAgent: class {
    setMessages = vi.fn();
    constructor() {
      createdAgents.push(this);
    }
  },
  useRenderTool: () => undefined,
  useConfigureSuggestions: () => undefined,
  // ThinkingIndicator (still rendered directly in DeskBody, unrelated to
  // the IntelligenceSlot change) calls useAgent to watch the stream.
  useAgent: () => ({ agent: { subscribe: () => ({ unsubscribe: () => undefined }) } }),
}));
vi.mock("./useDeskInterrupt", () => ({ useDeskInterrupt: () => undefined }));
vi.mock("./displays/useToolDisplay", () => ({ useToolDisplay: () => undefined }));
vi.mock("../layout/IntelligenceSlot", () => ({ useIntelligenceSlot: () => undefined }));

import { DeskView } from "./DeskView";

describe("DeskView", () => {
  it("enables chat attachments with an onUpload handler", () => {
    render(<DeskView threadId="t1" />);
    const props = chatProps[chatProps.length - 1];
    const attachments = props.attachments as { enabled: boolean; onUpload: unknown };
    expect(attachments.enabled).toBe(true);
    expect(typeof attachments.onUpload).toBe("function");
  });

  it("includes the saved workspace path as attachment metadata the model can read", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ path: "uploads/ab12_report.pdf" }) }));
    render(<DeskView threadId="t1" />);
    const props = chatProps[chatProps.length - 1];
    const attachments = props.attachments as { onUpload: (f: File) => Promise<{ type: string; value: string; metadata?: Record<string, unknown> }> };
    const file = new File(["x"], "report.pdf", { type: "application/pdf" });
    const result = await attachments.onUpload(file);
    expect(result).toEqual({
      type: "url",
      value: "uploads/ab12_report.pdf",
      metadata: { filename: "report.pdf", note: "Read this with read_text_file at path uploads/ab12_report.pdf if relevant." },
    });
  });

  it("seeds the agent's messages from the thread's history on mount", async () => {
    const history = [{ id: "u1", role: "user", content: "AAPL price?" }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => history }));
    render(<DeskView threadId="clients_17" />);
    await vi.waitFor(() => {
      expect(createdAgents[createdAgents.length - 1].setMessages).toHaveBeenCalledWith(history);
    });
  });

  it("does not call setMessages when the thread has no history yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    render(<DeskView threadId="clients_18" />);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(createdAgents[createdAgents.length - 1].setMessages).not.toHaveBeenCalled();
  });
});
