import { describe, it, expect } from "vitest";
import { reduceActivity, type AgUiEvent, type DeskActivity } from "./activity";

function run(events: AgUiEvent[], start = 1000, step = 100): DeskActivity[] {
  return events.reduce<DeskActivity[]>((acc, e, i) => reduceActivity(acc, e, start + i * step), []);
}

describe("reduceActivity", () => {
  it("maps each specialist node to its badge", () => {
    const names: Array<[string, string]> = [
      ["rag_agent", "RAG"], ["finance_agent", "FINANCE"], ["portfolio_agent", "PORTFOLIO"],
      ["browser_agent", "BROWSER"], ["email_agent", "EMAIL"], ["filesystem_agent", "FILES"],
      ["memory_agent", "MEMORY"],
    ];
    for (const [stepName, label] of names) {
      const [row] = run([{ type: "STEP_STARTED", stepName }]);
      expect(row).toMatchObject({ kind: "specialist", label });
    }
  });

  it("ignores supervisor, middleware and internal steps", () => {
    const rows = run([
      { type: "STEP_STARTED", stepName: "record_question" },
      { type: "STEP_STARTED", stepName: "supervisor" },
      { type: "STEP_STARTED", stepName: "model" },
      { type: "STEP_STARTED", stepName: "tools" },
      { type: "STEP_STARTED", stepName: "SummarizationMiddleware.before_model" },
      { type: "TEXT_MESSAGE_CONTENT", delta: "hi" },
    ]);
    expect(rows).toEqual([]);
  });

  it("tracks a tool call with its duration", () => {
    const rows = run([
      { type: "TOOL_CALL_START", toolCallId: "c1", toolCallName: "portfolio_metrics" },
      { type: "TOOL_CALL_ARGS", toolCallId: "c1", delta: "{}" },
      { type: "TOOL_CALL_END", toolCallId: "c1" },
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ kind: "tool", name: "portfolio_metrics", status: "done", durationMs: 200 });
  });

  it("an end for an unknown tool call changes nothing", () => {
    expect(run([{ type: "TOOL_CALL_END", toolCallId: "nope" }])).toEqual([]);
  });

  it("RUN_FINISHED with an interrupt outcome becomes an awaiting row", () => {
    const [row] = run([{ type: "RUN_FINISHED", outcome: { type: "interrupt", interrupts: [] } }]);
    expect(row.kind).toBe("awaiting");
  });

  it("RUN_FINISHED becomes a done row with total tokens", () => {
    expect(run([{ type: "RUN_FINISHED", usage: { totalTokens: 1234 } }])[0])
      .toMatchObject({ kind: "done", totalTokens: 1234 });
    expect(run([{ type: "RUN_FINISHED", usage: { inputTokens: 10, outputTokens: 5 } }])[0])
      .toMatchObject({ kind: "done", totalTokens: 15 });
    expect(run([{ type: "RUN_FINISHED" }])[0]).toMatchObject({ kind: "done", totalTokens: null });
  });

  it("RUN_ERROR becomes an error row", () => {
    const [row] = run([{ type: "RUN_ERROR", message: "boom" }]);
    expect(row).toMatchObject({ kind: "error", message: "boom" });
  });

  it("does not mutate its input", () => {
    const before: DeskActivity[] = [];
    reduceActivity(before, { type: "STEP_STARTED", stepName: "rag_agent" }, 1);
    expect(before).toEqual([]);
  });
});
