import { describe, it, expect } from "vitest";
import { readApproval } from "./approvals";

const email = { name: "send_email", args: { recipient: "a@x.com", subject: "Hi", body: "B" } };

function interrupt(raw: unknown) {
  return { id: "i1", reason: "langgraph:interrupt", metadata: { langgraph: { raw } } };
}

describe("readApproval", () => {
  it("reads action requests and their allowed decisions", () => {
    const got = readApproval(interrupt({
      action_requests: [email],
      review_configs: [{ action_name: "send_email", allowed_decisions: ["approve", "reject"] }],
    }));
    expect(got.requests).toEqual([email]);
    expect(got.allowed).toEqual([["approve", "reject"]]);
  });

  it("defaults to all three decisions when no config matches", () => {
    const got = readApproval(interrupt({ action_requests: [email] }));
    expect(got.allowed).toEqual([["approve", "edit", "reject"]]);
  });

  it("returns no requests for a malformed interrupt", () => {
    expect(readApproval(null).requests).toEqual([]);
    expect(readApproval(interrupt({ foo: 1 })).requests).toEqual([]);
    expect(readApproval(interrupt({ action_requests: [{ nope: true }] })).requests).toEqual([]);
  });
});
