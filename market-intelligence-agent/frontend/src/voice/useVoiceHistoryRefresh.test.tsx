import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const getThreadHistory = vi.fn();
vi.mock("../lib/api", () => ({ getThreadHistory: (...a: unknown[]) => getThreadHistory(...a) }));

import { useVoiceHistoryRefresh } from "./useVoiceHistoryRefresh";
import type { VoiceActivityEvent } from "./types";

const ev = (sequence: number, kind: VoiceActivityEvent["kind"]): VoiceActivityEvent => ({
  sequence, run_id: "r1", kind, name: null, tool_call_id: null, duration_ms: null, message: null,
});

describe("useVoiceHistoryRefresh", () => {
  beforeEach(() => {
    getThreadHistory.mockReset();
  });

  it("does nothing for non-trigger events", () => {
    const setMessages = vi.fn();
    renderHook(() => useVoiceHistoryRefresh("t1", [ev(1, "tool_started")], setMessages));
    expect(getThreadHistory).not.toHaveBeenCalled();
  });

  it("refetches history and sets messages on run_finished", async () => {
    const history = [{ id: "v1", role: "user", content: "spoken", source: "voice" }];
    getThreadHistory.mockResolvedValue(history);
    const setMessages = vi.fn();
    renderHook(() => useVoiceHistoryRefresh("t1", [ev(1, "run_finished")], setMessages));
    await waitFor(() => expect(setMessages).toHaveBeenCalledWith(history));
    expect(getThreadHistory).toHaveBeenCalledWith("t1");
  });

  it("refetches once per new trigger sequence", async () => {
    getThreadHistory.mockResolvedValue([]);
    const setMessages = vi.fn();
    const { rerender } = renderHook(
      ({ events }) => useVoiceHistoryRefresh("t1", events, setMessages),
      { initialProps: { events: [ev(1, "approval_required"), ev(2, "run_finished")] } },
    );
    await waitFor(() => expect(getThreadHistory).toHaveBeenCalledTimes(1));
    rerender({ events: [ev(1, "approval_required"), ev(2, "run_finished")] });
    rerender({ events: [ev(1, "approval_required"), ev(2, "run_finished"), ev(3, "tool_started")] });
    await waitFor(() => expect(getThreadHistory).toHaveBeenCalledTimes(1));
    rerender({ events: [ev(1, "approval_required"), ev(2, "run_finished"), ev(3, "tool_started"), ev(4, "run_finished")] });
    await waitFor(() => expect(getThreadHistory).toHaveBeenCalledTimes(2));
  });

  it("keeps messages and reports an error when the refetch fails", async () => {
    getThreadHistory.mockRejectedValue(new Error("thread history 500"));
    const setMessages = vi.fn();
    const { result } = renderHook(() => useVoiceHistoryRefresh("t1", [ev(1, "run_finished")], setMessages));
    await waitFor(() => expect(result.current.refreshError).toBe("Could not refresh the conversation"));
    expect(setMessages).not.toHaveBeenCalled();
  });

  it("still applies the result when another event arrives mid-fetch", async () => {
    let resolve!: (h: unknown[]) => void;
    getThreadHistory.mockReturnValue(new Promise((r) => { resolve = r; }));
    const setMessages = vi.fn();
    const { rerender } = renderHook(
      ({ events }) => useVoiceHistoryRefresh("t1", events, setMessages),
      { initialProps: { events: [ev(1, "run_finished")] } },
    );
    rerender({ events: [ev(1, "run_finished"), ev(2, "tool_started")] });
    const history = [{ id: "v1", role: "assistant", content: "spoken", source: "voice" }];
    resolve(history);
    await waitFor(() => expect(setMessages).toHaveBeenCalledWith(history));
    expect(getThreadHistory).toHaveBeenCalledTimes(1);
  });
});
