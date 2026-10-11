import { describe, expect, it } from "vitest";

import { mergeHistory } from "./mergeHistory";

const toolCallMsg = {
  id: "a1",
  role: "assistant",
  content: "",
  toolCalls: [{ id: "tc1", type: "function", function: { name: "portfolio_metrics", arguments: "{}" } }],
};
const toolResult = { id: "t1", role: "tool", content: "{}", toolCallId: "tc1" };

describe("mergeHistory", () => {
  it("keeps existing messages that carry tool calls", () => {
    const current = [{ id: "u1", role: "user", content: "q" }, toolCallMsg, toolResult];
    const merged = mergeHistory(current as never, [{ id: "u1", role: "user", content: "q" }]);
    expect(merged).toEqual(current);
  });

  it("appends only unseen ids, in history order", () => {
    const current = [{ id: "u1", role: "user", content: "q" }];
    const history = [
      { id: "u1", role: "user", content: "q" },
      { id: "v2", role: "user", content: "spoken", source: "voice" },
      { id: "v3", role: "assistant", content: "answer", source: "voice" },
    ];
    const merged = mergeHistory(current as never, history as never);
    expect(merged.map((m) => m.id)).toEqual(["u1", "v2", "v3"]);
  });

  it("leaves messages untouched for empty history", () => {
    const current = [toolCallMsg];
    expect(mergeHistory(current as never, [])).toEqual(current);
  });
});
