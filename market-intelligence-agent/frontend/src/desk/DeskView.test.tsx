import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

const chatProps: Record<string, unknown>[] = [];
vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  CopilotChat: (props: Record<string, unknown>) => {
    chatProps.push(props);
    return null;
  },
  HttpAgent: class {},
  useRenderTool: () => undefined,
  useConfigureSuggestions: () => undefined,
  // DeskActivityRail (rendered alongside CopilotChat) calls useAgent to
  // subscribe to the agent's event stream; give it an inert stub.
  useAgent: () => ({ agent: { subscribe: () => ({ unsubscribe: () => undefined }) } }),
}));
vi.mock("./useDeskInterrupt", () => ({ useDeskInterrupt: () => undefined }));
vi.mock("./displays/useToolDisplay", () => ({ useToolDisplay: () => undefined }));

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
});
