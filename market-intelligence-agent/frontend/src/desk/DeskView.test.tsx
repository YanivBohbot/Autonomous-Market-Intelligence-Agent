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
});
