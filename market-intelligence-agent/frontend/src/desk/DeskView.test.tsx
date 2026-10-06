import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const chatProps: Record<string, unknown>[] = [];
const providerProps: Record<string, unknown>[] = [];
const suggestionConfigs: Record<string, unknown>[] = [];
const portalContents: React.ReactNode[] = [];
const createdAgents: { setMessages: ReturnType<typeof vi.fn> }[] = [];

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: (props: Record<string, unknown> & { children: React.ReactNode }) => {
    providerProps.push(props);
    return <>{props.children}</>;
  },
  CopilotChat: (props: Record<string, unknown>) => {
    chatProps.push(props);
    return <div data-testid="copilot-chat" />;
  },
  HttpAgent: class {
    setMessages = vi.fn();
    constructor() {
      createdAgents.push(this);
    }
  },
  useRenderTool: () => undefined,
  useConfigureSuggestions: (config: Record<string, unknown>) => {
    suggestionConfigs.push(config);
  },
  useAgent: () => ({ agent: { subscribe: () => ({ unsubscribe: () => undefined }) } }),
}));
vi.mock("./useDeskInterrupt", () => ({ useDeskInterrupt: () => undefined }));
vi.mock("./displays/useToolDisplay", () => ({ useToolDisplay: () => undefined }));
vi.mock("./DeskActivityRail", () => ({ DeskActivityRail: () => <div data-testid="desk-activity-rail" /> }));
vi.mock("../layout/IntelligenceSlot", () => ({
  useIntelligenceSlot: (content: React.ReactNode) => {
    portalContents.push(content);
    return <div data-testid="intelligence-portal">{content}</div>;
  },
}));

import { MARKET_DESK_AGENT_ID } from "./constants";
import { DeskView } from "./DeskView";

describe("DeskView", () => {
  beforeEach(() => {
    chatProps.length = 0;
    providerProps.length = 0;
    suggestionConfigs.length = 0;
    portalContents.length = 0;
    createdAgents.length = 0;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
  });

  it("shows a compact Research workspace identity", () => {
    render(<DeskView threadId="research_1" />);

    expect(screen.getByRole("heading", { name: "Research workspace" })).toBeInTheDocument();
    expect(screen.getByText(/multi-agent market research/i)).toBeInTheDocument();
  });

  it("keeps the provider agent map and latest-message filter", () => {
    render(<DeskView threadId="research_2" />);
    const props = providerProps[providerProps.length - 1];
    const agentMap = props.agents__unsafe_dev_only as Record<string, unknown>;
    const messageFilter = props.messageFilter as (messages: unknown[]) => unknown[];

    expect(props.agentId).toBe(MARKET_DESK_AGENT_ID);
    expect(agentMap[MARKET_DESK_AGENT_ID]).toBe(createdAgents[createdAgents.length - 1]);
    expect(messageFilter(["old", "latest"])).toEqual(["latest"]);
    expect(props.showDevConsole).toBe(false);
    expect(props.enableInspector).toBe(false);
  });

  it("keeps the exact thread, attachment contract, static composer, and modern root class", () => {
    render(<DeskView threadId="clients_17" />);
    const props = chatProps[chatProps.length - 1];
    const attachments = props.attachments as { enabled: boolean; maxSize: number; onUpload: unknown };
    const input = props.input as { positioning: string; className: string; textArea: string; sendButton: string };

    expect(props.agentId).toBe(MARKET_DESK_AGENT_ID);
    expect(props.threadId).toBe("clients_17");
    expect(props.className).toContain("finance-desk-chat");
    expect(attachments.enabled).toBe(true);
    expect(attachments.maxSize).toBe(20 * 1024 * 1024);
    expect(typeof attachments.onUpload).toBe("function");
    expect(input.positioning).toBe("static");
    expect(input.className).toContain("border-t");
    expect(input.textArea).toContain("focus:border-terminal-accent");
    expect(input.sendButton).toContain("bg-terminal-accent");
  });

  it("keeps all three suggestions permanently available", () => {
    render(<DeskView threadId="research_3" />);
    const config = suggestionConfigs[suggestionConfigs.length - 1] as {
      available: string;
      suggestions: { title: string; message: string }[];
    };

    expect(config.available).toBe("always");
    expect(config.suggestions).toEqual([
      { title: "Portfolio value", message: "What is the total value of a client's portfolio?" },
      { title: "Stock price", message: "What is AAPL trading at?" },
      { title: "Concentration risk", message: "Are any clients over-concentrated in one stock?" },
    ]);
  });

  it("keeps DeskActivityRail inside the Intelligence portal", () => {
    render(<DeskView threadId="research_4" />);

    expect(portalContents).toHaveLength(1);
    expect(screen.getByTestId("intelligence-portal")).toContainElement(screen.getByTestId("desk-activity-rail"));
  });

  it("includes the saved workspace path as attachment metadata the model can read", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ path: "uploads/ab12_report.pdf" }) }));
    render(<DeskView threadId="t1" />);
    const props = chatProps[chatProps.length - 1];
    const attachments = props.attachments as { onUpload: (file: File) => Promise<{ type: string; value: string; metadata?: Record<string, unknown> }> };
    const file = new File(["x"], "report.pdf", { type: "application/pdf" });

    const result = await attachments.onUpload(file);

    expect(result).toEqual({
      type: "url",
      value: "uploads/ab12_report.pdf",
      metadata: { filename: "report.pdf", note: "Read this with read_text_file at path uploads/ab12_report.pdf if relevant." },
    });
  });

  it("seeds the same agent from the thread history", async () => {
    const history = [{ id: "u1", role: "user", content: "AAPL price?" }];
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => history }));
    render(<DeskView threadId="clients_17" />);

    await vi.waitFor(() => {
      expect(createdAgents[createdAgents.length - 1].setMessages).toHaveBeenCalledWith(history);
    });
  });

  it("does not seed an agent when the thread has no history", async () => {
    render(<DeskView threadId="clients_18" />);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(createdAgents[createdAgents.length - 1].setMessages).not.toHaveBeenCalled();
  });
});
