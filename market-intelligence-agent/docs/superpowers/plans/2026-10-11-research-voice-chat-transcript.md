# Research Voice Chat Transcript Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show spoken Research turns in the React chat (live user caption, then committed user and assistant messages) and remove the Streamlit UI, the `/classic` route and the code only they used, without regressing anything already built.

**Architecture:** The live caption comes straight from the GPT-Live WebRTC data channel (`session.input_transcript.delta`) inside `useResearchVoice`. Committed turns come from the checkpoint: the backend stops hiding voice-tagged messages in `/copilot/market-desk/history` and in AG-UI snapshots, and `DeskView` refetches history whenever a polled voice activity event reports `run_finished` or `approval_required`. Removals are done bottom-up (backend, then frontend, then Streamlit and docs), each followed by the full suites.

**Tech Stack:** FastAPI, LangGraph multi-agent graph, OpenAI GPT-Live (WebRTC + sideband), React 19 + CopilotKit v2, Vitest, pytest, uv.

**Spec:** `docs/superpowers/specs/2026-10-11-research-voice-chat-transcript-design.md`

## Global Constraints

- All commands run from `market-intelligence-agent/` (this worktree's project dir). Python via `uv run`. Frontend commands from `frontend/`.
- Backend suite: `uv run pytest tests/ -q`. Frontend suite: `npm test`. Frontend build: `npm run build`.
- Answer display is one block (no token streaming of the assistant reply).
- `/stream`, `/approve`, `/invocations` and the AgentCore deployment must not change behavior.
- Documentation files are edited, never deleted.
- No transcript text is ever written to `VoiceActivityStore` (the existing test `test_voice_state_endpoint_is_incremental_and_contains_no_transcript` must stay green).
- After every task: run the full backend and frontend suites. The only allowed drop in test count is deliberately deleted tests of removed code, named in the commit message.
- Never reuse a real client thread id (`clients_<id>`) for manual checks or QA. Use fresh ids prefixed `qa-`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- The optional mic badge from the spec is **not** built (YAGNI). The history API still returns `source` so it can be added later.

## Review Focus

1. **Two refetch triggers in one poll.** A single poll can return both `approval_required` and `run_finished`, or a refetch can still be in flight when the next event arrives. Expected: exactly one refetch per new trigger sequence, no duplicate messages, and the latest history wins. Pinned in Task 3 ("refetches once per new trigger sequence").
2. **Empty transcript.** The delegation fires with no deltas (silence or noise). Expected: no empty caption bubble and no blank user message. Pinned in Task 2 ("ignores empty deltas") and backed by the worker's existing `if not question: continue`.
3. **Disconnect mid-utterance.** The user clicks End while the caption is half-filled. Expected: the caption is cleared and does not linger after voice ends. Pinned in Task 2 ("clears caption on cleanup").
4. **Old clients sending `surface: "classic"`** (a cached old bundle). Expected: a clear 422 instead of silently starting a different graph. Pinned in Task 4.
5. **Summarization message plus voice messages in the same thread.** Removing the voice filter must not un-hide the summary. Pinned in Task 1 (the summary is still excluded while voice is included).

---

### Task 0: Regression baseline

**Files:**
- Create: `docs/superpowers/qa/2026-10-11-voice-transcript-baseline.md`

- [ ] **Step 1: Run the backend suite and record the result**

Run: `uv run pytest tests/ -q 2>&1 | tail -5`
Record the passed, failed, skipped and error counts, plus the name of every failing test.

- [ ] **Step 2: Run the frontend suite and build**

Run (in `frontend/`): `npm test 2>&1 | tail -8` and `npm run build 2>&1 | tail -5`
Record the test file count, test count, failures, and build status.

- [ ] **Step 3: Write the baseline file**

```markdown
# Baseline — 2026-10-11 (before voice transcript work)

Branch: feat/product-ui-modernization @ <git rev-parse --short HEAD>

| Suite | Passed | Failed | Skipped | Notes |
|---|---|---|---|---|
| Backend pytest | <n> | <n> | <n> | <failing test names or "none"> |
| Frontend vitest | <n> | <n> | – | <files: n> |
| Frontend build | ok/fail | | | |

Pre-existing failures are NOT fixed as part of this work; they are reported.
```

Fill in the real numbers. Do not leave the `<n>` placeholders.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/qa/2026-10-11-voice-transcript-baseline.md
git commit -m "test(qa): record regression baseline before voice transcript work"
```

If either suite has pre-existing failures, stop and report them to the user before Task 1.

---

### Task 1: Backend shows voice turns in history and snapshots

**Files:**
- Modify: `app/api/routers/copilot.py` (`_is_voice` usage in `MarketDeskAgent._filter_orphan_tool_messages` around line 54, and `market_desk_history` around lines 135-160)
- Test: `tests/unit/test_copilot_endpoint.py` (replace `test_history_and_snapshots_hide_voice_turns_but_checkpoint_retains_them` around line 303)

**Interfaces:**
- Produces: `GET /copilot/market-desk/history?thread_id=…` returns `list[{"id": str, "role": "user"|"assistant", "content": str, "source": "voice"|"text"}]`, including voice-tagged messages. Summarization messages are still excluded.

- [ ] **Step 1: Replace the old test with the new expectation**

In `tests/unit/test_copilot_endpoint.py`, delete `test_history_and_snapshots_hide_voice_turns_but_checkpoint_retains_them` and add:

```python
def test_history_and_snapshots_include_voice_turns_tagged_with_source(finance_client):
    client, app = finance_client
    graph = app.state.market_desk_agent.graph
    cfg = {"configurable": {"thread_id": "voice-history"}}
    messages = [
        HumanMessage(content="Here is a summary of the conversation to date: ...", id="s1",
                     additional_kwargs={"lc_source": "summarization"}),
        HumanMessage(content="typed question", id="typed-1"),
        AIMessage(content="typed answer", id="typed-2"),
        HumanMessage(content="spoken question", id="voice-1", additional_kwargs={"source": "voice"}),
        AIMessage(content="spoken answer", id="voice-2", additional_kwargs={"source": "voice"}),
    ]
    graph.update_state(cfg, {"messages": messages})

    response = client.get(f"{PATH}/history", params={"thread_id": "voice-history"})

    assert response.status_code == 200
    body = response.json()
    assert [(m["content"], m["source"]) for m in body] == [
        ("typed question", "text"),
        ("typed answer", "text"),
        ("spoken question", "voice"),
        ("spoken answer", "voice"),
    ]

    filtered = app.state.market_desk_agent._filter_orphan_tool_messages(messages)
    assert [m.content for m in filtered] == [
        "typed question",
        "typed answer",
        "spoken question",
        "spoken answer",
    ]
```

- [ ] **Step 2: Run it and verify it fails**

Run: `uv run pytest tests/unit/test_copilot_endpoint.py -k "voice_turns or history" -v`
Expected: the new test FAILS (voice messages missing, `KeyError: 'source'`). The other history tests pass.

- [ ] **Step 3: Implement**

In `app/api/routers/copilot.py`:

1. Replace `_is_voice` with a source reader:

```python
def _source(message) -> str:
    return "voice" if getattr(message, "additional_kwargs", {}).get("source") == "voice" else "text"
```

2. In `MarketDeskAgent._filter_orphan_tool_messages`:

```python
        visible = [m for m in messages if not _is_summary(m)]
```

Also update the class docstring: voice turns are now shown, see the 2026-10-11 spec.

3. In `market_desk_history`, build each item with the source and drop the `_is_voice` condition:

```python
    return [
        {
            "id": m.id,
            "role": "user" if isinstance(m, HumanMessage) else "assistant",
            "content": m.content,
            "source": _source(m),
        }
        for m in messages
        if isinstance(m, (HumanMessage, AIMessage))
        and isinstance(m.content, str)
        and m.content
        and not _is_summary(m)
    ]
```

Update its docstring: replace "and voice turns (_is_voice) are left out" with "voice turns are included and tagged `source: "voice"` (2026-10-11 spec)".

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/unit/test_copilot_endpoint.py tests/unit/test_multi_agent_voice_history.py -v`
Expected: all PASS. `grep -n "_is_voice" app/` returns nothing.

- [ ] **Step 5: Full regression and commit**

Run: `uv run pytest tests/ -q` (counts = baseline). Then:

```bash
git add app/api/routers/copilot.py tests/unit/test_copilot_endpoint.py
git commit -m "feat(voice): include spoken Research turns in chat history

Replaces test_history_and_snapshots_hide_voice_turns_but_checkpoint_retains_them
with test_history_and_snapshots_include_voice_turns_tagged_with_source."
```

---

### Task 2: Live caption in `useResearchVoice`

**Files:**
- Modify: `frontend/src/voice/useResearchVoice.ts` (state block near line 46, `cleanup` near line 67, `start` near line 147, `channel.onmessage` near line 178, the return object)
- Test: `frontend/src/voice/useResearchVoice.test.tsx`

**Interfaces:**
- Produces: `useResearchVoice(...)` returns an additional `liveCaption: string`. `ResearchVoiceContextValue` inherits it automatically, since it is `ReturnType<typeof useResearchVoice> & …`.

- [ ] **Step 1: Write the failing tests**

Append inside `describe("useResearchVoice", …)`:

```tsx
  it("accumulates input transcript deltas into liveCaption and clears on delegation", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ session_id: "s1", sdp: "answer-sdp" }));
    const { result } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());

    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta", delta: "Which clients " }));
    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta", delta: "are concentrated?" }));
    expect(result.current.liveCaption).toBe("Which clients are concentrated?");

    act(() => peers[0].channel.emit({ type: "session.delegation.created" }));
    expect(result.current.liveCaption).toBe("");
  });

  it("ignores empty deltas", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ session_id: "s1", sdp: "answer-sdp" }));
    const { result } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());

    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta", delta: "" }));
    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta" }));
    expect(result.current.liveCaption).toBe("");
  });

  it("clears caption on cleanup", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ session_id: "s1", sdp: "answer-sdp" }));
    const { result } = renderHook(() => useResearchVoice("thread-1", true));
    await act(async () => result.current.start());
    act(() => peers[0].channel.emit({ type: "session.input_transcript.delta", delta: "half a sent" }));

    act(() => peers[0].channel.emit({ type: "session.closed" }));
    expect(result.current.liveCaption).toBe("");
  });
```

- [ ] **Step 2: Run them and verify they fail**

Run (in `frontend/`): `npx vitest run src/voice/useResearchVoice.test.tsx`
Expected: 3 new FAIL (`liveCaption` is undefined). The existing tests pass.

- [ ] **Step 3: Implement**

In `useResearchVoice.ts`:

```ts
  const [liveCaption, setLiveCaption] = useState("");
```

In `cleanup`, next to `setActive(false);`:

```ts
      setLiveCaption("");
```

In `start`, next to `setError(null);`:

```ts
    setLiveCaption("");
```

In `channel.onmessage`, widen the parsed type and add two branches before the `session.closed` branch:

```ts
        let message: { type?: string; delta?: string };
        // ...
        if (message.type === "session.started") {
          setPhase("listening");
          startPolling();
        } else if (message.type === "session.input_transcript.delta") {
          const delta = message.delta;
          if (delta) setLiveCaption((current) => current + delta);
        } else if (message.type === "session.delegation.created") {
          setLiveCaption("");
        } else if (message.type === "session.closed") {
```

Add `liveCaption` to the returned object (after `error`).

- [ ] **Step 4: Run the tests and verify they pass**

Run: `npx vitest run src/voice/`
Expected: all PASS.

- [ ] **Step 5: Full regression and commit**

Run: `npm test` (count = baseline + 3) and `npm run build`. Then:

```bash
git add frontend/src/voice/useResearchVoice.ts frontend/src/voice/useResearchVoice.test.tsx
git commit -m "feat(voice): expose live Research voice caption from the data channel"
```

---

### Task 3: DeskView renders the caption and refreshes history on voice turns

**Files:**
- Create: `frontend/src/voice/LiveCaptionBubble.tsx`
- Create: `frontend/src/voice/useVoiceHistoryRefresh.ts`
- Modify: `frontend/src/desk/DeskView.tsx` (pass `agent` to `DeskBody`, render the bubble, call the hook)
- Modify: `frontend/src/lib/api.ts:152-156` (`ThreadMessage` gains `source?: "voice" | "text"`)
- Test: `frontend/src/voice/useVoiceHistoryRefresh.test.tsx`, `frontend/src/voice/LiveCaptionBubble.test.tsx`, `frontend/src/desk/DeskView.test.tsx`

**Interfaces:**
- Consumes: `liveCaption: string` and `events: VoiceActivityEvent[]` from `useResearchVoiceContext()` (Task 2), and `getThreadHistory(threadId)` from `lib/api`.
- Produces: `useVoiceHistoryRefresh(threadId: string, events: VoiceActivityEvent[] | undefined, setMessages: (m: ThreadMessage[]) => void): { refreshError: string | null }`, and `<LiveCaptionBubble text={string} />`.

- [ ] **Step 1: Write the failing hook test**

`frontend/src/voice/useVoiceHistoryRefresh.test.tsx`:

```tsx
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
  beforeEach(() => getThreadHistory.mockReset());

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
});
```

- [ ] **Step 2: Run it and verify it fails**

Run: `npx vitest run src/voice/useVoiceHistoryRefresh.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the hook**

`frontend/src/voice/useVoiceHistoryRefresh.ts`:

```ts
import { useEffect, useRef, useState } from "react";

import { getThreadHistory, type ThreadMessage } from "../lib/api";
import type { VoiceActivityEvent } from "./types";

const TRIGGERS = new Set<VoiceActivityEvent["kind"]>(["run_finished", "approval_required"]);

// Spoken turns are written to the checkpoint by the voice worker, not by
// CopilotKit, so the chat never sees them on its own. When a voice turn
// finishes (or pauses for approval), reload the thread's history -- the same
// call DeskView makes on mount -- so the spoken question and answer appear.
export function useVoiceHistoryRefresh(
  threadId: string,
  events: VoiceActivityEvent[] | undefined,
  setMessages: (messages: ThreadMessage[]) => void,
): { refreshError: string | null } {
  const handledRef = useRef(0);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  useEffect(() => {
    // A new voice session resets both the events list and the server-side
    // sequence counter, so forget what was handled when the list empties.
    if (!events?.length) {
      handledRef.current = 0;
      return;
    }
    const latestTrigger = events.reduce(
      (max, item) => (TRIGGERS.has(item.kind) && item.sequence > max ? item.sequence : max),
      0,
    );
    if (latestTrigger <= handledRef.current) return;
    handledRef.current = latestTrigger;
    let active = true;
    getThreadHistory(threadId)
      .then((history) => {
        if (!active) return;
        setMessages(history);
        setRefreshError(null);
      })
      .catch(() => {
        if (active) setRefreshError("Could not refresh the conversation");
      });
    return () => {
      active = false;
    };
  }, [events, setMessages, threadId]);

  return { refreshError };
}
```

- [ ] **Step 4: Run the hook test and verify it passes**

Run: `npx vitest run src/voice/useVoiceHistoryRefresh.test.tsx`
Expected: 4 PASS.

- [ ] **Step 5: Write the failing bubble test**

`frontend/src/voice/LiveCaptionBubble.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { LiveCaptionBubble } from "./LiveCaptionBubble";

describe("LiveCaptionBubble", () => {
  it("renders the live text with an accessible label", () => {
    render(<LiveCaptionBubble text="Which clients are" />);
    const bubble = screen.getByRole("status", { name: "You are speaking" });
    expect(bubble).toHaveTextContent("Which clients are");
  });

  it("renders nothing for empty text", () => {
    const { container } = render(<LiveCaptionBubble text="" />);
    expect(container).toBeEmptyDOMElement();
  });
});
```

- [ ] **Step 6: Implement the bubble**

`frontend/src/voice/LiveCaptionBubble.tsx`:

```tsx
// User-side bubble for the words GPT-Live is hearing right now. It is a
// transient caption: once the turn ends it clears, and the committed user
// message arrives through the history refresh.
export function LiveCaptionBubble({ text }: { text: string }) {
  if (!text) return null;
  return (
    <div className="flex justify-end px-4 pb-2">
      <div
        role="status"
        aria-label="You are speaking"
        aria-live="polite"
        className="max-w-[80%] rounded-2xl rounded-br-sm border border-dashed border-terminal-accent/50 bg-terminal-accent/10 px-3.5 py-2 text-sm italic text-terminal-text"
      >
        <span aria-hidden="true" className="mr-1.5">🎤</span>
        {text}
        <span aria-hidden="true" className="ml-1 animate-pulse">▍</span>
      </div>
    </div>
  );
}
```

Run: `npx vitest run src/voice/LiveCaptionBubble.test.tsx`. Expected: 2 PASS.

- [ ] **Step 7: Write the failing DeskView integration tests**

In `frontend/src/desk/DeskView.test.tsx`, add `vi.mock("../lib/api", …)` only if it is not already mocked. Check the top of the file first: `getThreadHistory` is called on mount, so the file likely already stubs `fetch` or `../lib/api`. Reuse whichever mechanism exists. Then add:

```tsx
  it("shows the live caption bubble while the user speaks", () => {
    voiceHookState = { ...voiceHookState, liveCaption: "Which clients are" };
    render(<DeskView threadId="desk_t1" voiceEnabled />);
    expect(screen.getByRole("status", { name: "You are speaking" })).toHaveTextContent("Which clients are");
  });

  it("reloads chat history into the agent when a voice run finishes", async () => {
    const history = [{ id: "v1", role: "assistant", content: "spoken answer", source: "voice" }];
    getThreadHistoryMock.mockResolvedValue(history);
    voiceHookState = {
      ...voiceHookState,
      events: [{ sequence: 1, run_id: "r", kind: "run_finished", name: null, tool_call_id: null, duration_ms: null, message: null }],
    };
    render(<DeskView threadId="desk_t1" voiceEnabled />);
    await waitFor(() => expect(createdAgents.at(-1)!.setMessages).toHaveBeenCalledWith(history));
  });
```

`getThreadHistoryMock` is the `vi.fn()` behind the file's `../lib/api` mock. If the file has no such mock yet, add at the top:

```tsx
const getThreadHistoryMock = vi.fn().mockResolvedValue([]);
vi.mock("../lib/api", async (orig) => ({
  ...(await orig<typeof import("../lib/api")>()),
  getThreadHistory: (...a: unknown[]) => getThreadHistoryMock(...a),
}));
```

Also make sure the default `voiceHookState` in `beforeEach` includes `liveCaption: ""` and `events: []`. Import `waitFor` from `@testing-library/react`.

Run: `npx vitest run src/desk/DeskView.test.tsx`. Expected: the 2 new tests FAIL.

- [ ] **Step 8: Wire it into DeskView**

In `frontend/src/desk/DeskView.tsx`:

```tsx
import { LiveCaptionBubble } from "../voice/LiveCaptionBubble";
import { useVoiceHistoryRefresh } from "../voice/useVoiceHistoryRefresh";
```

Pass the agent down. Both `<DeskBody threadId={threadId} />` usages become `<DeskBody threadId={threadId} agent={agent} />`. In `DeskBody`:

```tsx
function DeskBody({ threadId, agent }: { threadId: string; agent: HttpAgent }) {
  const voice = useResearchVoiceContext();
  const setMessages = useCallback(
    (messages: ThreadMessage[]) => agent.setMessages(messages),
    [agent],
  );
  const { refreshError } = useVoiceHistoryRefresh(threadId, voice?.events, setMessages);
```

(Import `useCallback` from react and `type ThreadMessage` from `../lib/api`.)

Render, just before `<CopilotChat …>`:

```tsx
        {refreshError && (
          <p role="alert" className="mx-4 mb-1 rounded-lg border border-terminal-warn/40 bg-terminal-warn/10 px-3 py-1.5 text-xs text-terminal-warn">
            {refreshError}
          </p>
        )}
```

Render, just after `</CopilotChat>` (still inside `<main>`), so the caption sits above the composer area:

```tsx
        <LiveCaptionBubble text={voice?.liveCaption ?? ""} />
```

If visual placement during QA puts the bubble below the composer, move it into an absolutely positioned wrapper `className="pointer-events-none absolute inset-x-4 bottom-24 z-30"`, mirroring the approval overlay. Decide this in the QA task, not here.

In `lib/api.ts`:

```ts
export interface ThreadMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  source?: "voice" | "text";
}
```

- [ ] **Step 9: Run the tests and verify they pass**

Run: `npx vitest run src/desk src/voice`. Expected: all PASS.

- [ ] **Step 10: Full regression and commit**

Run: `npm test` and `npm run build` (clean), and `uv run pytest tests/ -q` (unchanged). Then:

```bash
git add frontend/src/voice/LiveCaptionBubble.tsx frontend/src/voice/LiveCaptionBubble.test.tsx \
  frontend/src/voice/useVoiceHistoryRefresh.ts frontend/src/voice/useVoiceHistoryRefresh.test.tsx \
  frontend/src/desk/DeskView.tsx frontend/src/desk/DeskView.test.tsx frontend/src/lib/api.ts
git commit -m "feat(voice): show live caption and spoken turns in the Research chat"
```

---

### Task 4: Remove the backend Classic voice path and transcript endpoint

**Files:**
- Delete: `app/voice/transcript_store.py`, `app/voice/graph.py`, `tests/unit/test_voice_transcript.py`, `tests/unit/test_voice_graph_structure.py`
- Modify: `app/api/routers/gptlive_session.py` (drop the transcript endpoint, `voice_agent_app` and the classic branching; the research path becomes unconditional)
- Modify: `app/voice/worker.py` (drop `_handle_delegation`, `GREETING`, the `surface` parameter's classic path and all `transcript_store` calls)
- Modify: `app/voice/hitl.py` (drop `is_interrupted`, `resume_with`; keep `classify_verdict`)
- Modify: `app/api/server.py:18,63` (drop `build_voice_agent_app` import and `app.state.voice_agent_app`)
- Modify: `app/api/models/models.py` (`GptLiveSessionRequest.surface: Literal["research"] = "research"`; delete `VoiceTranscriptEntry`, `VoiceTranscriptResponse`)
- Modify tests: `tests/unit/test_gptlive_session.py`, `tests/unit/test_server_wiring.py`, `tests/unit/test_research_voice_api.py`, and `tests/unit/test_stream.py` (comment only)

**Interfaces:**
- Produces: `POST /gptlive/session` accepts only `surface` = `"research"` (or omitted, which defaults to research). `"classic"` returns 422. `GET /voice/{thread_id}/transcript` returns 404. `run_delegation_worker(session_id, thread_id, *, research_runtime, activity_store, lease, turn_coordinator)` no longer takes `agent_app` or `surface`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_research_voice_api.py`, using its `voice_api` fixture:

```python
def test_classic_surface_is_rejected(voice_api):
    client, create, captured = voice_api
    response = client.post(
        "/gptlive/session",
        json={"sdp": "offer-sdp", "surface": "classic"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 422
    create.assert_not_awaited()
    assert "worker" not in captured


def test_transcript_endpoint_is_gone(voice_api):
    client, _, _ = voice_api
    assert client.get("/voice/any-thread/transcript").status_code == 404
```

The `voice_api` fixture yields `(TestClient, create_mock, captured)`, where `captured["worker"] == (args, kwargs)` of the spawned worker. Replace `test_omitted_surface_preserves_classic_worker_contract` with:

```python
def test_omitted_surface_defaults_to_research(voice_api):
    client, create, captured = voice_api

    response = client.post(
        "/gptlive/session",
        json={"sdp": "offer-sdp", "thread_id": "default-thread"},
        headers={"Origin": "http://127.0.0.1:5173"},
    )

    assert response.status_code == 200
    assert response.json() == {"session_id": "live-session-1", "sdp": "answer-sdp"}
    args, kwargs = captured["worker"]
    assert args == ("live-session-1", "default-thread")
    assert "surface" not in kwargs
    assert kwargs["research_runtime"] is app.state.research_voice_runtime
    assert kwargs["activity_store"] is app.state.voice_activity_store
    assert kwargs["lease"] is not None
    create.assert_awaited_once()
```

Remove the `app.state.voice_agent_app = object()` line from the fixture. In `test_research_session_acquires_lease_and_passes_shared_dependencies`, delete any assertion on `kwargs["surface"]` or on a third positional `agent_app` argument, since the new signature has neither.

In `test_research_worker_does_not_write_transcripts_and_releases_lease`, remove the `transcript_store` import and its final assertion, since the module no longer exists. The test's other assertions (lease released, no transcript in state) remain.

- [ ] **Step 2: Run them and verify they fail**

Run: `uv run pytest tests/unit/test_research_voice_api.py -v`
Expected: `test_classic_surface_is_rejected` FAILS (200, not 422) and `test_transcript_endpoint_is_gone` FAILS (200, not 404).

- [ ] **Step 3: Implement the removals**

1. `models.py`: `surface: Literal["research"] = "research"`. Delete `VoiceTranscriptEntry` and `VoiceTranscriptResponse`.
2. `gptlive_session.py`: remove the imports of `VoiceTranscriptResponse`, `transcript_store` and `is_interrupted`. Remove the `get_voice_transcript` route. In `create_session`, delete `is_research` and make the research block unconditional (lease, activity store, pending-approval check). Use `thread_id = research_thread_id`. Call:

```python
    worker_coro = run_delegation_worker(
        session_id,
        thread_id,
        research_runtime=research_runtime,
        activity_store=activity_store,
        lease=lease,
        turn_coordinator=coordinator,
    )
```

The `if lease is not None` guards become plain statements, since the lease is always set.

3. `worker.py`: delete `GREETING`, `_extract_reply` (if only the classic path used it; grep first), `_handle_delegation`, and the `transcript_store` and `is_interrupted, resume_with` imports. Change the signature to:

```python
async def run_delegation_worker(
    session_id: str,
    thread_id: str,
    *,
    research_runtime,
    activity_store,
    lease,
    turn_coordinator,
) -> None:
```

Then inline `is_research = True`: remove every `if is_research` / `if not is_research` branch, keep the research bodies, and drop the dependency `ValueError` check. Keep the greeting as `RESEARCH_GREETING`.

4. `hitl.py`: delete `is_interrupted` and `resume_with`, and any import they alone used (`Command` if unused).
5. `server.py`: delete the `build_voice_agent_app` import and the `app.state.voice_agent_app = …` line.
6. Delete `app/voice/transcript_store.py` and `app/voice/graph.py`.
7. Tests:
   - Delete `tests/unit/test_voice_transcript.py` and `tests/unit/test_voice_graph_structure.py`.
   - In `test_gptlive_session.py`, delete the tests that set `voice_agent_app` / `surface="classic"` (around lines 25-105). Keep any research-only tests.
   - In `test_server_wiring.py`, delete the `build_voice_agent_app` monkeypatch line.
   - In `test_stream.py:216`, reword the comment so it no longer cites `hitl.py`'s `is_interrupted` ("matching the nested-interrupt detection in `_helpers.pending_interrupt_from_snapshot`").

- [ ] **Step 4: Verify nothing references the removed code**

Run: `grep -rn "transcript_store\|voice_agent_app\|build_voice_agent_app\|app.voice.graph\|is_interrupted\|resume_with\|VoiceTranscript\|_handle_delegation" app tests --include=*.py`
Expected: no output.

- [ ] **Step 5: Run the tests and verify they pass**

Run: `uv run pytest tests/unit/test_research_voice_api.py tests/unit/test_gptlive_session.py tests/unit/test_server_wiring.py tests/unit/test_voice_hitl_classify.py -v`, then `uv run pytest tests/ -q`
Expected: all PASS. The count equals the previous count minus the deleted tests plus 2 new ones.

- [ ] **Step 6: Commit (name every deleted test)**

```bash
git add -A app tests
git commit -m "refactor(voice): remove Classic voice path and transcript endpoint

Research is the only voice surface; surface=classic now returns 422.
Deleted tests (removed code): tests/unit/test_voice_transcript.py,
tests/unit/test_voice_graph_structure.py, classic cases in
tests/unit/test_gptlive_session.py, test_omitted_surface_preserves_classic_worker_contract
(replaced by test_omitted_surface_defaults_to_research)."
```

List the exact deleted test function names from `git diff --stat` and the diff itself in the message.

---

### Task 5: Remove the React `/classic` route and its components

**Files:**
- Modify: `frontend/src/App.tsx` (delete `ClassicChat`, its imports and the `/classic` route; unused `useState`/`useRef`/`FormEvent`/`KeyboardEvent` imports go too)
- Delete (only if unused after the App edit, checked with grep): `frontend/src/components/ChatPane.tsx`, `VoicePanel.tsx`, `ApprovalCard.tsx`, `ApprovalCard.test.tsx`, `ActivityRail.tsx`, `frontend/src/hooks/useChatStream.ts` (and its test, if any)
- Modify: `frontend/src/lib/api.ts` (delete `postApprove` and any `/stream` client helper if nothing else imports them)
- Modify: `frontend/src/setupTests.ts` (drop any classic-specific setup it references)
- Test: `frontend/src/App.test.tsx`

**Interfaces:**
- Produces: the router no longer has `/classic`. An unknown path renders whatever the app already does for unmatched routes. The test asserts the old classic chat is absent.

- [ ] **Step 1: Write the failing test**

In `frontend/src/App.test.tsx`, following its existing `MemoryRouter` render helper:

```tsx
  it("no longer serves the classic chat at /classic", () => {
    renderAt("/classic"); // use the file's existing helper name
    expect(screen.queryByPlaceholderText("Ask the agent…")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Toggle voice")).not.toBeInTheDocument();
  });
```

Delete any existing App tests that assert the classic chat renders.

Run: `npx vitest run src/App.test.tsx`. Expected: the new test FAILS.

- [ ] **Step 2: Remove the route and component**

Edit `App.tsx`: delete the `ClassicChat` function and the `<Route path="/classic" …/>` line, plus the imports of `ChatPane`, `ActivityRail`, `ApprovalCard`, `VoicePanel` and `useChatStream`, and the React hooks only `ClassicChat` used. Keep `newThreadId` if `App` still uses it.

- [ ] **Step 3: Delete orphaned files**

For each candidate, run `grep -rln "<Name>" frontend/src --include=*.ts --include=*.tsx | grep -v "<own file>"`, with `<Name>` in `ChatPane`, `VoicePanel`, `ApprovalCard`, `ActivityRail`, `useChatStream`, `postApprove`. Delete the file, or the function in `lib/api.ts`, only when the grep is empty, and delete their tests with them. `desk/ApprovalPanel` and `desk/DeskActivityRail` are different components and stay.

- [ ] **Step 4: Run the tests and build**

Run: `npm test` and `npm run build`
Expected: all PASS and a clean `tsc -b` (no unused-import errors). The count equals the previous count, minus the deleted classic tests, plus 1.

- [ ] **Step 5: Commit (name deleted tests)**

```bash
git add -A frontend/src
git commit -m "refactor(ui): remove the Classic chat route and its components

Deleted tests (removed code): <list files/tests from the diff>."
```

---

### Task 6: Remove Streamlit and update the docs

**Files:**
- Delete: `app/ui/app.py`, `app/ui/voice_panel.py` (and `app/ui/` itself), plus any test that imports `app.ui` (`grep -rln "app.ui\|app/ui" tests`; `tests/unit/test_workspace_screenshots.py` references it, so read it and remove only the Streamlit-specific cases)
- Modify: `pyproject.toml:30` (remove `"streamlit>=1.51.0"`), then `uv lock` (regenerates `uv.lock`)
- Modify: `docker-compose.yml` (delete the `ui:` service, roughly lines 19-35)
- Modify docs: `CLAUDE.md`, `README.md`, `docs/VOICE.md`, `docs/superpowers/specs/2026-10-08-multi-agent-voice-research-design.md` (superseded note only)

**Interfaces:** none (removal and docs).

- [ ] **Step 1: Delete the Streamlit code and dependency**

```bash
git rm -r app/ui
uv remove streamlit
```

`uv remove` edits `pyproject.toml` and `uv.lock` together. Verify that `requirements.agentcore.txt` does not list streamlit: `grep -n streamlit requirements.agentcore.txt`. Expected: no output. If it does list it, remove that line.

- [ ] **Step 2: Remove the compose service**

Delete the whole `ui:` service block from `docker-compose.yml`, from `ui:` through its `restart:` line. Leave `api:` untouched. Validate with `docker compose config -q` if Docker is available. If it is not, check by eye that the YAML is still valid (the indentation of `api:` is intact).

- [ ] **Step 3: Fix tests referencing Streamlit**

Run: `grep -rn "app\.ui\|app/ui\|streamlit" tests app --include=*.py`
For each hit in `tests/`, delete the Streamlit-only test function. If a test covers shared behavior and only mentions Streamlit in a comment, keep it and reword the comment. Expected after the edits: no output.

- [ ] **Step 4: Update the docs (edit, never delete files)**

- `CLAUDE.md`:
  - Remove the "Run the Streamlit frontend (port 8080)" command block lines.
  - In "Voice mode", retitle to "Voice mode (`app/voice/`, React Research)". Delete the "Classic Streamlit voice …" paragraph and the `app/ui/voice_panel.py` bullet. Add: "Spoken turns are shown in the Research chat: a live caption from `session.input_transcript.delta` while speaking, then the committed user/assistant messages, reloaded from `/copilot/market-desk/history` on `run_finished`/`approval_required` (see `docs/superpowers/specs/2026-10-11-research-voice-chat-transcript-design.md`)."
  - In the `gptlive_session.py` router bullet, replace "omitted/`classic` preserves the legacy path" with "`surface` must be `research` (default); `classic` is rejected with 422".
  - In "Multi-agent mode", delete "Classic voice remains on `app.state.voice_agent_app`." and change the console route list to `(/research, /briefing, /clients, /reports, /data)`.
  - In "Legacy single-agent graph", replace "and the temporary Classic voice workflow" with "(no runtime caller remains; removal is a tracked follow-up)".
- `README.md`: replace the Streamlit run command (line ~131) with the React console command (`cd frontend && npm install && npm run dev`) and change "Open the UI at http://localhost:8080" to "http://localhost:5173". Update the Tech Stack line "Frontend UI: Streamlit" to "Frontend UI: React 19 + Vite + Tailwind (CopilotKit / AG-UI)".
- `docs/VOICE.md`:
  - Replace the run steps (lines ~32-33) with "open http://localhost:5173/research and press the mic in the composer".
  - Delete the `classic → app.state.voice_agent_app` diagram branch and the `surface: "research" | "classic"` wording.
  - Replace the line-96 transcript-endpoint paragraph with the new live-caption plus history-refresh description.
  - Drop `localhost:8080` and the Streamlit upgrade tip from troubleshooting.
- `docs/superpowers/specs/2026-10-08-multi-agent-voice-research-design.md`: add directly under its title:

```markdown
> **Superseded in part (2026-10-11):** voice transcripts ARE now shown in the Research chat, and the Classic/Streamlit voice surface was removed. See `2026-10-11-research-voice-chat-transcript-design.md`.
```

- [ ] **Step 5: Verify that no stale references remain**

Run: `grep -rn -i "streamlit\|app/ui\|localhost:8080\|/classic\|voice_agent_app\|/transcript" CLAUDE.md README.md docs/VOICE.md docker-compose.yml pyproject.toml`
Expected: no output, apart from the browser tool's unrelated "investor-relations transcripts" wording in README, which stays.

- [ ] **Step 6: Full regression and commit**

Run: `uv sync`, then `uv run pytest tests/ -q`, then (in `frontend/`) `npm test` and `npm run build`. All green. Then:

```bash
git add -A app pyproject.toml uv.lock docker-compose.yml CLAUDE.md README.md docs tests
git commit -m "refactor: remove Streamlit UI; docs describe React Research voice

Deleted tests (removed code): <list, or 'none'>."
```

---

### Task 7: Final regression gate and code review

**Files:**
- Modify: `docs/superpowers/qa/2026-10-11-voice-transcript-baseline.md` (append an "After" table)

- [ ] **Step 1: Run the full suites and the build**

Run: `uv run pytest tests/ -q`, then (in `frontend/`) `npm test` and `npm run build`.
Expected: all green.

- [ ] **Step 2: Reconcile the counts against the baseline**

Append to the baseline file:

```markdown
## After (end of implementation)

| Suite | Baseline | Deleted (removed code) | Added | Expected | Actual |
|---|---|---|---|---|---|
| Backend | <n> | <n> | <n> | <n> | <n> |
| Frontend | <n> | <n> | <n> | <n> | <n> |
```

Expected must equal Actual. Investigate any mismatch before moving on.

- [ ] **Step 3: Run the dead-import sweep**

Run: `grep -rn "app\.ui\|transcript_store\|app\.voice\.graph\|voice_agent_app" app tests --include=*.py` and `grep -rn "VoicePanel\|ChatPane\|ClassicChat\|useChatStream" frontend/src`
Expected: no output.

- [ ] **Step 4: Run the code review**

Use superpowers:requesting-code-review on the full diff `git diff 80d2a08..HEAD`. Fix every Critical or Important finding with a test, re-run Steps 1-3, and commit.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/qa/2026-10-11-voice-transcript-baseline.md
git commit -m "test(qa): reconcile regression counts after voice transcript work"
```

---

### Task 8: Live QA pass

**Files:**
- Create: `docs/superpowers/qa/2026-10-11-voice-transcript-qa.md`

Setup:
1. Stop any stale backend on :8000 and Streamlit on :8080. If a process cannot be stopped because permission is denied, ask the user to stop it.
2. Start the backend without `--reload` from this worktree: `uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000`.
3. Start the frontend from this worktree: `cd frontend && npm run dev`.
4. Open `http://localhost:5173` in Chrome. Use the claude-in-chrome tools if connected; otherwise ask the user to drive the voice steps and report what they see.

Use only fresh `qa-` threads ("New session" in the UI).

- [ ] **Step 1: Run the QA matrix and record each row with evidence**

| # | Check | Pass criterion (grounded) |
|---|---|---|
| 1 | Voice transcript | Say "Which clients have more than 30 percent of their portfolio in one stock?". The caption grows while speaking, then a user message plus an assistant message appear, audio plays, and both remain after reload. The answer's client names match `concentration_screen` output in the backend log. |
| 2 | Voice HITL | Say "Send an email to <a client name from customers.db> with a summary of their portfolio". The approval card appears. Click Reject or say "reject". The backend log shows no SES send, and the chat shows the cancellation. |
| 3 | Typed concentration | The same question typed: the activity rail shows `portfolio_agent` and `concentration_screen`, and the names match the DB. |
| 4 | RAG | "What does Amazon's 2024 annual report say about AI?" gives an answer containing `[Source:` and `page`. |
| 5 | Market data | "What is Apple's current stock price?" gives a number matching `yfinance_get_ticker_info` in the log. |
| 6 | Typed HITL approve | "Write a file qa-note.txt with the text hello" then Approve. `data/workspace/qa-note.txt` exists with `hello`. Delete it afterwards. |
| 7 | Voice-to-text continuity | After row 1 in the same thread, type "summarize that in one sentence". The answer refers to the concentration result. |
| 8 | Briefing | `/briefing` shows indices, movers, news and client alerts, with no red errors in the console. |
| 9 | Clients and Reports | `/clients` lists clients, one workspace opens, and `/reports` generates one report. |
| 10 | Data | `/data` lists documents and clients (no import). |
| 11 | Removed surfaces | `/classic` shows no classic chat, `curl -s -o /dev/null -w "%{http_code}" localhost:8000/voice/x/transcript` returns `404`, and nothing listens on :8080. |
| 12 | Backend API | `curl localhost:8000/health` returns ok. `POST /stream` with a `qa-` thread and an email request emits `interrupted`, then `POST /approve` with `approved:false` returns a completed status. |
| 13 | Browser specialist | "Open https://www.example.com and tell me the page title" → activity rail shows `browser_agent` + `browser_navigate`/`browser_snapshot`; answer says "Example Domain". |
| 14 | Memory specialist | "Remember that my preferred report format is Excel" → approval card for `save_memory` → Approve; then new message "What is my preferred report format?" → `memory_agent` + `recall_memory`/`list_memories`, answer "Excel". |
| 15 | Supervisor routing summary | Across rows 3–6, 13, 14 every one of the 7 specialists (rag, finance, portfolio, browser, email, filesystem, memory) was routed to at least once — list which row proved each. |

- [ ] **Step 2: Handle failures**

For each failing row: find the root cause, write a regression test that reproduces it, fix it, re-run the suites, commit, and re-run that QA row only. Do not repeat rows just because the LLM worded an answer differently.

- [ ] **Step 3: Write the user-runnable QA guide (French)**

The user explicitly asked to be able to re-run every QA check themselves. Create `docs/QA-GUIDE.md` **in French**, one section per matrix row (1–15), each with:
- **Objectif** (one line: which part of the multi-agent system it proves),
- **Prérequis** (servers running, URL, fresh session via "New session"),
- **Étapes** (numbered: where to click, exact text to type or say),
- **Résultat attendu** (what must appear in the chat, in the Intelligence/activity rail — specialist + tool names — and in the backend log or on disk),
- **Si ça échoue** (first thing to check: backend log line, server restarted, mic permission, `.env` key).
Top of the file: how to start backend + frontend (exact commands from this worktree), and a warning that the email test with "approve" sends a real SES email (only to `clients.email` addresses) — use "reject" to test safely. Include the curl commands for rows 11–12 verbatim.

- [ ] **Step 4: Write the QA report and commit**

`docs/superpowers/qa/2026-10-11-voice-transcript-qa.md`: one row per check with Pass/Fail, the evidence (log line, screenshot path or curl output), and any fix commit. Then:

```bash
git add docs/superpowers/qa/2026-10-11-voice-transcript-qa.md docs/QA-GUIDE.md
git commit -m "test(qa): live QA pass + user QA guide for Research voice transcript"
```

- [ ] **Step 5: Report to the user**

Summarize in French and point the user to `docs/QA-GUIDE.md`: the regression counts (baseline → after), the QA results per row, the fixes made, and what remains (for example the `app/agent/graph.py` follow-up). The branch is not merged or pushed without the user's explicit request.
