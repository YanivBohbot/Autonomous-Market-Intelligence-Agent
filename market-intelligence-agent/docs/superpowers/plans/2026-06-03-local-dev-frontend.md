# Local Dev Test Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished React+Vite+Tailwind local-dev frontend that exercises the Market Intelligence Agent's chat streaming, HITL approval, live agent activity, health/session controls, and voice against the local FastAPI backend.

**Architecture:** A new SPA in `market-intelligence-agent/frontend/` calls the existing FastAPI backend on `:8000`. The Vite dev server proxies API paths to `:8000` (no CORS issues). One additive backend change adds a `node` SSE event so the UI can show live graph/tool activity. Logic-bearing units (SSE parser, chat stream hook, approval state machine, API client) are built test-first with Vitest; presentational components get functional reference implementations that the frontend-specialist agent then elevates visually.

**Tech Stack:** React 18, TypeScript, Vite 5, Tailwind CSS 3, Vitest + React Testing Library, `livekit-client` (voice). Backend: FastAPI, LangGraph 1.x, pytest.

**Prerequisites:** Node.js 20+ and npm installed locally. Backend runnable via `uv run uvicorn app.api.server:app --port 8000 --reload`.

**Conventions:**
- All `cd` paths are relative to the repo root `market-intelligence-agent/`.
- Backend tests: `uv run pytest tests/unit/<file> -v`.
- Frontend tests: `npm test` (run inside `frontend/`).
- Commit after each task. Branch: create `feat/local-dev-frontend` before Task 1.

---

## Task 0: Create feature branch

- [ ] **Step 1: Create and switch to the branch**

Run (from repo root):
```bash
git checkout -b feat/local-dev-frontend
```
Expected: `Switched to a new branch 'feat/local-dev-frontend'`

---

## Task 1: Backend — emit a `node` SSE event from `/stream`

**Files:**
- Modify: `app/api/routers/stream.py`
- Modify: `tests/unit/test_stream.py`

The current handler calls `agent_app.astream(inputs, config, stream_mode="messages")` and iterates `(token, meta)`. We switch to `stream_mode=["updates", "messages"]`, which makes the iterator yield `(mode, chunk)` tuples. For `mode == "messages"`, `chunk` is the existing `(token, meta)`. For `mode == "updates"`, `chunk` is `{node_name: state_update}` and we emit a new `node` event. The token/interrupted/done/error events keep their exact shapes.

- [ ] **Step 1: Update the existing test fake + happy-path test to the multi-mode shape**

Replace the `_FakeAgentApp.astream` and `_ExplodingAgentApp.astream` so they yield `(mode, chunk)` tuples, and update the happy-path test to also assert a `node` event is emitted. In `tests/unit/test_stream.py`, replace the `_FakeAgentApp` class with:

```python
class _FakeAgentApp:
    """Stand-in for agent_app with controllable multi-mode astream + get_state."""

    def __init__(self, tokens, updates=(), next_after=(), state_messages=None):
        # tokens: list[(AIMessageChunk, meta_dict)]  -> emitted as ("messages", (tok, meta))
        # updates: list[dict]                         -> emitted as ("updates", {node: state})
        self._tokens = tokens
        self._updates = updates
        self._next_after = next_after
        self._state_messages = state_messages or []

    def astream(self, inputs, config, stream_mode):
        async def gen():
            for upd in self._updates:
                yield "updates", upd
            for tok, meta in self._tokens:
                yield "messages", (tok, meta)

        return gen()

    async def aget_state(self, config):
        return SimpleNamespace(
            next=self._next_after,
            values={"messages": self._state_messages},
        )
```

Then update `_ExplodingAgentApp.astream` to match the multi-mode signature (it still raises immediately):

```python
    def astream(self, inputs, config, stream_mode):
        async def gen():
            raise RuntimeError(self._error_message)
            yield  # pragma: no cover - makes this an async generator

        return gen()
```

(The `_ExplodingAgentApp` body is unchanged in behavior; only confirm it accepts `stream_mode`.)

- [ ] **Step 2: Add a new test for the `node` event**

Add this test to `tests/unit/test_stream.py`:

```python
def test_stream_emits_node_events_for_graph_updates():
    tokens = [
        (AIMessageChunk(content="Hi"), {"langgraph_node": "generate"}),
    ]
    tool_msg = AIMessage(
        content="",
        tool_calls=[
            {"id": "c1", "name": "yfinance_get_ticker_info", "args": {"ticker": "AMZN"}}
        ],
    )
    updates = [
        {"rag": {"messages": []}},
        {"generate": {"messages": [tool_msg]}},
    ]
    fake = _FakeAgentApp(tokens, updates=updates, next_after=())

    app.state.agent_app = fake
    client = TestClient(app)
    response = client.post("/stream", json={"query": "AMZN?", "thread_id": "t-node"})

    assert response.status_code == 200
    events = _parse_sse(response.text)

    node_events = [d for e, d in events if e == "node"]
    assert {"node": "rag", "tool_calls": None} in node_events
    assert {"node": "generate", "tool_calls": ["yfinance_get_ticker_info"]} in node_events
    assert events[-1][0] == "done"
```

- [ ] **Step 3: Run the stream tests to verify the new test fails**

Run:
```bash
uv run pytest tests/unit/test_stream.py -v
```
Expected: `test_stream_emits_node_events_for_graph_updates` FAILS (no `node` events yet); existing tests may also fail because the handler still passes `stream_mode="messages"` while the fake now yields `(mode, chunk)` tuples — this is expected before Step 4.

- [ ] **Step 4: Rewrite the stream handler to consume multi-mode and emit `node`**

Replace the body of the `try:` loop in `app/api/routers/stream.py`. The full file becomes:

```python
import logging
from collections.abc import AsyncIterable

from fastapi import APIRouter, Request
from fastapi.sse import EventSourceResponse, ServerSentEvent
from langchain_core.messages import AIMessageChunk

from app.api.models.models import StreamRequest
from app.api.routers._helpers import get_action_description

logger = logging.getLogger(__name__)
router = APIRouter()


def _tool_names_from_update(update) -> list[str] | None:
    """Pull tool-call names off the last message in a node's state update."""
    if not isinstance(update, dict):
        return None
    messages = update.get("messages")
    if not messages:
        return None
    last = messages[-1]
    tool_calls = getattr(last, "tool_calls", None)
    if not tool_calls:
        return None
    return [tc["name"] for tc in tool_calls]


@router.post("/stream", response_class=EventSourceResponse)
async def stream_endpoint(
    request: Request, payload: StreamRequest
) -> AsyncIterable[ServerSentEvent]:
    agent_app = request.app.state.agent_app
    config = {
        "configurable": {
            "thread_id": payload.thread_id,
            "actor_id": "mia-agent",
        }
    }
    inputs = {"question": payload.query}

    try:
        async for mode, chunk in agent_app.astream(
            inputs, config, stream_mode=["updates", "messages"]
        ):
            if mode == "updates":
                for node_name, update in chunk.items():
                    yield ServerSentEvent(
                        data={
                            "node": node_name,
                            "tool_calls": _tool_names_from_update(update),
                        },
                        event="node",
                    )
            elif mode == "messages":
                token, meta = chunk
                if (
                    isinstance(token, AIMessageChunk)
                    and meta.get("langgraph_node") == "generate"
                    and token.content
                    and not getattr(token, "tool_call_chunks", None)
                ):
                    yield ServerSentEvent(
                        data={"token": token.content}, event="token"
                    )

        snapshot = await agent_app.aget_state(config)
        if snapshot.next:
            last_msg = snapshot.values["messages"][-1]
            action = get_action_description(last_msg)
            yield ServerSentEvent(
                data={"action": action, "next_step": str(snapshot.next)},
                event="interrupted",
            )
        else:
            yield ServerSentEvent(data={}, event="done")
    except Exception as exc:
        logger.exception("stream failed for thread %s", payload.thread_id)
        yield ServerSentEvent(data={"error": str(exc)}, event="error")
```

- [ ] **Step 5: Run the full stream test file to verify all pass**

Run:
```bash
uv run pytest tests/unit/test_stream.py -v
```
Expected: all tests PASS (happy path, interrupted, error, and the new node test).

- [ ] **Step 6: Run the broader suite to confirm no regressions**

Run:
```bash
uv run pytest tests/unit/test_stream.py tests/unit/test_hitl_interrupt.py tests/unit/test_health.py -v
```
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add app/api/routers/stream.py tests/unit/test_stream.py
git commit -m "feat(api): emit 'node' SSE event for live agent activity"
```

---

## Task 2: Frontend scaffold (Vite + TS + Tailwind + Vitest)

**Files:**
- Create: `frontend/package.json`, `frontend/index.html`, `frontend/vite.config.ts`,
  `frontend/tsconfig.json`, `frontend/tsconfig.node.json`, `frontend/tailwind.config.ts`,
  `frontend/postcss.config.js`, `frontend/src/main.tsx`, `frontend/src/index.css`,
  `frontend/src/vite-env.d.ts`, `frontend/vitest.config.ts`, `frontend/src/setupTests.ts`,
  `frontend/.gitignore`

- [ ] **Step 1: Create `frontend/package.json`**

```json
{
  "name": "mia-dev-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "livekit-client": "^2.5.5",
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-markdown": "^9.0.1"
  },
  "devDependencies": {
    "@testing-library/jest-dom": "^6.4.8",
    "@testing-library/react": "^16.0.1",
    "@testing-library/user-event": "^14.5.2",
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "autoprefixer": "^10.4.20",
    "jsdom": "^25.0.0",
    "postcss": "^8.4.45",
    "tailwindcss": "^3.4.10",
    "typescript": "^5.5.4",
    "vite": "^5.4.3",
    "vitest": "^2.0.5"
  }
}
```

- [ ] **Step 2: Create config files**

`frontend/.gitignore`:
```
node_modules
dist
*.local
```

`frontend/index.html`:
```html
<!doctype html>
<html lang="en" class="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>MIA · Dev Console</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`frontend/vite.config.ts` (proxies API paths to the backend on :8000):
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const API_TARGET = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/stream": { target: API_TARGET, changeOrigin: true },
      "/approve": { target: API_TARGET, changeOrigin: true },
      "/health": { target: API_TARGET, changeOrigin: true },
      "/livekit": { target: API_TARGET, changeOrigin: true },
    },
  },
});
```

`frontend/vitest.config.ts`:
```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/setupTests.ts"],
  },
});
```

`frontend/src/setupTests.ts`:
```ts
import "@testing-library/jest-dom";
```

`frontend/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "types": ["vitest/globals", "@testing-library/jest-dom"]
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

`frontend/tsconfig.node.json`:
```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true,
    "strict": true
  },
  "include": ["vite.config.ts", "vitest.config.ts"]
}
```

`frontend/postcss.config.js`:
```js
export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
};
```

`frontend/tailwind.config.ts` (theme tokens for the fintech-terminal look — frontend-specialist may extend):
```ts
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        terminal: {
          bg: "#0a0e14",
          panel: "#0f1620",
          border: "#1c2733",
          text: "#c9d4e0",
          muted: "#6b7a8d",
          accent: "#34d399", // signal green
          warn: "#fbbf24", // amber: awaiting approval
          danger: "#f87171", // red: reject/error
        },
      },
      fontFamily: {
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
```

`frontend/src/index.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

html, body, #root { height: 100%; }
body { @apply bg-terminal-bg text-terminal-text font-sans antialiased; margin: 0; }
```

`frontend/src/vite-env.d.ts`:
```ts
/// <reference types="vite/client" />
```

`frontend/src/main.tsx`:
```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 3: Create a minimal `App.tsx` placeholder so the scaffold builds**

`frontend/src/App.tsx`:
```tsx
export default function App() {
  return <div className="p-6 font-mono text-terminal-accent">MIA Dev Console — scaffold OK</div>;
}
```

- [ ] **Step 4: Install dependencies and verify the build**

Run (inside `frontend/`):
```bash
cd frontend && npm install && npm run build
```
Expected: install completes; `vite build` succeeds with no TypeScript errors; a `dist/` folder is produced.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "chore(frontend): scaffold Vite + React + TS + Tailwind + Vitest"
```

---

## Task 3: SSE parser (`lib/sse.ts`) — test-first

**Files:**
- Create: `frontend/src/lib/sse.ts`, `frontend/src/lib/sse.test.ts`

The backend sends SSE frames as `event: <name>\n` + `data: <json>\n\n`. We need a pure parser that turns a growing text buffer into complete `{event, data}` records and returns the unconsumed remainder (frames can split across network chunks).

- [ ] **Step 1: Write the failing test**

`frontend/src/lib/sse.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { parseSseBuffer, type SseEvent } from "./sse";

describe("parseSseBuffer", () => {
  it("parses a single complete frame", () => {
    const buf = 'event: token\ndata: {"token":"Hi"}\n\n';
    const { events, rest } = parseSseBuffer(buf);
    expect(events).toEqual<SseEvent[]>([{ event: "token", data: { token: "Hi" } }]);
    expect(rest).toBe("");
  });

  it("parses multiple frames in one buffer", () => {
    const buf =
      'event: node\ndata: {"node":"rag","tool_calls":null}\n\n' +
      'event: token\ndata: {"token":"Hello"}\n\n';
    const { events } = parseSseBuffer(buf);
    expect(events.map((e) => e.event)).toEqual(["node", "token"]);
  });

  it("keeps an incomplete trailing frame in rest", () => {
    const buf = 'event: token\ndata: {"token":"Hi"}\n\nevent: tok';
    const { events, rest } = parseSseBuffer(buf);
    expect(events).toHaveLength(1);
    expect(rest).toBe("event: tok");
  });

  it("handles a data-only frame (no event line) as event 'message'", () => {
    const buf = 'data: {"x":1}\n\n';
    const { events } = parseSseBuffer(buf);
    expect(events[0].event).toBe("message");
    expect(events[0].data).toEqual({ x: 1 });
  });

  it("tolerates non-JSON data by passing the raw string", () => {
    const buf = "event: ping\ndata: keepalive\n\n";
    const { events } = parseSseBuffer(buf);
    expect(events[0].data).toBe("keepalive");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (inside `frontend/`):
```bash
npm test -- sse
```
Expected: FAIL — `./sse` cannot be resolved / `parseSseBuffer` not defined.

- [ ] **Step 3: Implement `lib/sse.ts`**

`frontend/src/lib/sse.ts`:
```ts
export interface SseEvent {
  event: string;
  data: unknown;
}

export interface ParseResult {
  events: SseEvent[];
  rest: string;
}

/**
 * Parse a growing SSE text buffer into complete frames.
 * Frames are separated by a blank line ("\n\n"). Any trailing partial
 * frame is returned in `rest` so the caller can prepend the next chunk.
 */
export function parseSseBuffer(buffer: string): ParseResult {
  const events: SseEvent[] = [];
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";

  for (const frame of parts) {
    if (!frame.trim()) continue;
    let event = "message";
    const dataLines: string[] = [];
    for (const line of frame.split("\n")) {
      if (line.startsWith("event:")) {
        event = line.slice("event:".length).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice("data:".length).trim());
      }
    }
    const raw = dataLines.join("\n");
    let data: unknown = raw;
    try {
      data = JSON.parse(raw);
    } catch {
      // leave as raw string (e.g. keepalive comments)
    }
    events.push({ event, data });
  }

  return { events, rest };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
npm test -- sse
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/sse.ts frontend/src/lib/sse.test.ts
git commit -m "feat(frontend): SSE buffer parser with tests"
```

---

## Task 4: API client + shared types (`lib/api.ts`, `lib/types.ts`)

**Files:**
- Create: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`

- [ ] **Step 1: Create shared types**

`frontend/src/lib/types.ts`:
```ts
export type Role = "user" | "assistant" | "error";

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
}

export interface ActivityItem {
  id: string;
  node: string;
  toolCalls: string[] | null;
  ts: number;
}

export interface PendingAction {
  action: string;
  nextStep: string;
}

export interface ApproveResponse {
  response: string;
  status: "completed" | "interrupted";
  next_step: string | null;
}

export interface HealthResponse {
  status: string;
  version: string;
}
```

- [ ] **Step 2: Create the API client**

`frontend/src/lib/api.ts`:
```ts
import type { ApproveResponse, HealthResponse } from "./types";

// In dev, Vite proxies these paths to the backend, so "" (same origin) works.
export const API_BASE = "";

export async function getHealth(base = API_BASE): Promise<HealthResponse> {
  const res = await fetch(`${base}/health`);
  if (!res.ok) throw new Error(`health ${res.status}`);
  return res.json();
}

export async function postApprove(
  threadId: string,
  approved: boolean,
  base = API_BASE,
): Promise<ApproveResponse> {
  const res = await fetch(`${base}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ thread_id: threadId, approved }),
  });
  if (!res.ok) throw new Error(`approve ${res.status}: ${await res.text()}`);
  return res.json();
}

export async function getLiveKitToken(
  identity: string,
  room: string,
  base = API_BASE,
): Promise<{ token: string; url: string; room: string }> {
  const res = await fetch(`${base}/livekit/token`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identity, room }),
  });
  if (!res.ok) throw new Error(`livekit token ${res.status}`);
  return res.json();
}

export function newThreadId(): string {
  const rand = Math.random().toString(36).slice(2, 10);
  return `web_session_${rand}`;
}
```

- [ ] **Step 3: Typecheck**

Run (inside `frontend/`):
```bash
npx tsc -b
```
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts
git commit -m "feat(frontend): API client and shared types"
```

---

## Task 5: Chat stream hook (`hooks/useChatStream.ts`)

**Files:**
- Create: `frontend/src/hooks/useChatStream.ts`

This hook owns the chat turn lifecycle: it POSTs to `/stream`, reads the streaming body with `fetch` + `ReadableStream`, feeds bytes through `parseSseBuffer`, and updates messages/activity/pendingAction. It is exercised indirectly via the App smoke test and manually; the parser it depends on is unit-tested in Task 3.

- [ ] **Step 1: Implement the hook**

`frontend/src/hooks/useChatStream.ts`:
```ts
import { useCallback, useRef, useState } from "react";
import { parseSseBuffer } from "../lib/sse";
import { API_BASE } from "../lib/api";
import type { ActivityItem, ChatMessage, PendingAction } from "../lib/types";

let idCounter = 0;
const nextId = () => `m${Date.now()}_${idCounter++}`;

export function useChatStream(threadId: string, base = API_BASE) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [pending, setPending] = useState<PendingAction | null>(null);
  const assistantIdRef = useRef<string | null>(null);

  const appendActivity = useCallback((node: string, toolCalls: string[] | null) => {
    setActivity((prev) => [...prev, { id: nextId(), node, toolCalls, ts: Date.now() }]);
  }, []);

  const send = useCallback(
    async (query: string) => {
      setMessages((prev) => [...prev, { id: nextId(), role: "user", content: query }]);
      const assistantId = nextId();
      assistantIdRef.current = assistantId;
      setMessages((prev) => [...prev, { id: assistantId, role: "assistant", content: "" }]);
      setStreaming(true);

      try {
        const res = await fetch(`${base}/stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, thread_id: threadId }),
        });
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { events, rest } = parseSseBuffer(buffer);
          buffer = rest;

          for (const ev of events) {
            const data = ev.data as Record<string, unknown>;
            if (ev.event === "token") {
              const tok = String(data.token ?? "");
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantId ? { ...m, content: m.content + tok } : m,
                ),
              );
            } else if (ev.event === "node") {
              appendActivity(
                String(data.node ?? "?"),
                (data.tool_calls as string[] | null) ?? null,
              );
            } else if (ev.event === "interrupted") {
              setPending({
                action: String(data.action ?? "Action requires approval."),
                nextStep: String(data.next_step ?? ""),
              });
            } else if (ev.event === "error") {
              setMessages((prev) => [
                ...prev,
                { id: nextId(), role: "error", content: String(data.error ?? "Unknown error") },
              ]);
            }
          }
        }
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: "error", content: (err as Error).message },
        ]);
      } finally {
        setStreaming(false);
      }
    },
    [base, threadId, appendActivity],
  );

  // Called by the approval flow to append the resumed result and update pending.
  const resolvePending = useCallback(
    (responseText: string, stillPending: PendingAction | null) => {
      if (responseText) {
        setMessages((prev) => [
          ...prev,
          { id: nextId(), role: "assistant", content: responseText },
        ]);
      }
      setPending(stillPending);
    },
    [],
  );

  const reset = useCallback(() => {
    setMessages([]);
    setActivity([]);
    setPending(null);
    setStreaming(false);
  }, []);

  return { messages, activity, streaming, pending, send, resolvePending, reset };
}
```

- [ ] **Step 2: Typecheck**

Run:
```bash
npx tsc -b
```
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useChatStream.ts
git commit -m "feat(frontend): chat stream hook (SSE token/node/interrupt handling)"
```

---

## Task 6: ApprovalCard (HITL) — test-first

**Files:**
- Create: `frontend/src/components/ApprovalCard.tsx`, `frontend/src/components/ApprovalCard.test.tsx`

`ApprovalCard` shows the pending action and Approve/Reject buttons. On click it calls `postApprove`, then invokes `onResolved(responseText, stillPending)` where `stillPending` is a new `PendingAction` if the backend returned `status === "interrupted"` (chained interrupt), else `null`.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/ApprovalCard.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApprovalCard } from "./ApprovalCard";
import * as api from "../lib/api";

describe("ApprovalCard", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("approves and reports completion", async () => {
    vi.spyOn(api, "postApprove").mockResolvedValue({
      response: "Email sent.",
      status: "completed",
      next_step: null,
    });
    const onResolved = vi.fn();
    render(
      <ApprovalCard
        threadId="t1"
        pending={{ action: "send_email to vip@example.com", nextStep: "('tools',)" }}
        onResolved={onResolved}
      />,
    );
    expect(screen.getByText(/send_email/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(api.postApprove).toHaveBeenCalledWith("t1", true);
    expect(onResolved).toHaveBeenCalledWith("Email sent.", null);
  });

  it("rejects and reports completion", async () => {
    vi.spyOn(api, "postApprove").mockResolvedValue({
      response: "Action cancelled.",
      status: "completed",
      next_step: null,
    });
    const onResolved = vi.fn();
    render(
      <ApprovalCard
        threadId="t1"
        pending={{ action: "write_file report.md", nextStep: "('tools',)" }}
        onResolved={onResolved}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /reject/i }));
    expect(api.postApprove).toHaveBeenCalledWith("t1", false);
    expect(onResolved).toHaveBeenCalledWith("Action cancelled.", null);
  });

  it("surfaces a chained interrupt as still-pending", async () => {
    vi.spyOn(api, "postApprove").mockResolvedValue({
      response: "Next action required: save_memory",
      status: "interrupted",
      next_step: "('tools',)",
    });
    const onResolved = vi.fn();
    render(
      <ApprovalCard
        threadId="t1"
        pending={{ action: "first action", nextStep: "('tools',)" }}
        onResolved={onResolved}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /approve/i }));
    expect(onResolved).toHaveBeenCalledWith(
      "Next action required: save_memory",
      { action: "Next action required: save_memory", nextStep: "('tools',)" },
    );
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run:
```bash
npm test -- ApprovalCard
```
Expected: FAIL — `./ApprovalCard` cannot be resolved.

- [ ] **Step 3: Implement `ApprovalCard.tsx`**

`frontend/src/components/ApprovalCard.tsx`:
```tsx
import { useState } from "react";
import { postApprove } from "../lib/api";
import type { PendingAction } from "../lib/types";

interface Props {
  threadId: string;
  pending: PendingAction;
  onResolved: (responseText: string, stillPending: PendingAction | null) => void;
}

export function ApprovalCard({ threadId, pending, onResolved }: Props) {
  const [busy, setBusy] = useState(false);

  async function decide(approved: boolean) {
    setBusy(true);
    try {
      const res = await postApprove(threadId, approved);
      const stillPending: PendingAction | null =
        res.status === "interrupted"
          ? { action: res.response, nextStep: res.next_step ?? "" }
          : null;
      onResolved(res.response, stillPending);
    } catch (err) {
      onResolved(`Approval failed: ${(err as Error).message}`, null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-terminal-warn/40 bg-terminal-warn/5 p-4">
      <div className="mb-1 font-mono text-xs uppercase tracking-wider text-terminal-warn">
        Awaiting approval
      </div>
      <p className="mb-3 font-mono text-sm text-terminal-text">{pending.action}</p>
      <div className="flex gap-2">
        <button
          disabled={busy}
          onClick={() => decide(true)}
          className="rounded bg-terminal-accent px-4 py-1.5 text-sm font-semibold text-terminal-bg disabled:opacity-50"
        >
          Approve
        </button>
        <button
          disabled={busy}
          onClick={() => decide(false)}
          className="rounded border border-terminal-danger px-4 py-1.5 text-sm font-semibold text-terminal-danger disabled:opacity-50"
        >
          Reject
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run:
```bash
npm test -- ApprovalCard
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ApprovalCard.tsx frontend/src/components/ApprovalCard.test.tsx
git commit -m "feat(frontend): HITL ApprovalCard with chained-interrupt handling"
```

---

## Task 7: Presentational components (ChatPane, ActivityRail, Header)

**Files:**
- Create: `frontend/src/components/ChatPane.tsx`, `frontend/src/components/ActivityRail.tsx`, `frontend/src/components/Header.tsx`

These are reference implementations: correct behavior + reasonable styling. The frontend-specialist agent elevates the visuals afterward.

- [ ] **Step 1: Create `ChatPane.tsx`**

```tsx
import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import type { ChatMessage } from "../lib/types";

const roleStyles: Record<ChatMessage["role"], string> = {
  user: "self-end bg-terminal-border/60 text-terminal-text",
  assistant: "self-start bg-terminal-panel text-terminal-text",
  error: "self-start bg-terminal-danger/10 text-terminal-danger border border-terminal-danger/40",
};

export function ChatPane({ messages, streaming }: { messages: ChatMessage[]; streaming: boolean }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-terminal-muted">
        <p className="font-mono text-sm">Ask the agent something. e.g. "What's AMZN trading at?"</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 overflow-y-auto p-4">
      {messages.map((m, i) => (
        <div
          key={m.id}
          className={`max-w-[80%] rounded-lg px-3 py-2 text-sm leading-relaxed ${roleStyles[m.role]}`}
        >
          <div className="prose prose-invert prose-sm max-w-none">
            <ReactMarkdown>
              {m.content + (streaming && m.role === "assistant" && i === messages.length - 1 ? " ▌" : "")}
            </ReactMarkdown>
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
```

- [ ] **Step 2: Create `ActivityRail.tsx`**

```tsx
import type { ActivityItem } from "../lib/types";

const nodeColor: Record<string, string> = {
  rag: "text-sky-400",
  grader: "text-violet-400",
  web_search: "text-amber-400",
  generate: "text-terminal-accent",
  tools: "text-pink-400",
};

export function ActivityRail({ activity }: { activity: ActivityItem[] }) {
  return (
    <aside className="flex h-full w-72 flex-col border-l border-terminal-border bg-terminal-panel">
      <div className="border-b border-terminal-border px-3 py-2 font-mono text-xs uppercase tracking-wider text-terminal-muted">
        Agent activity
      </div>
      <div className="flex-1 overflow-y-auto p-3 font-mono text-xs">
        {activity.length === 0 && <p className="text-terminal-muted">idle</p>}
        {activity.map((a) => (
          <div key={a.id} className="mb-2 border-l-2 border-terminal-border pl-2">
            <span className={nodeColor[a.node] ?? "text-terminal-text"}>{a.node}</span>
            {a.toolCalls && a.toolCalls.length > 0 && (
              <div className="mt-0.5 text-terminal-muted">→ {a.toolCalls.join(", ")}</div>
            )}
          </div>
        ))}
      </div>
    </aside>
  );
}
```

- [ ] **Step 3: Create `Header.tsx`**

```tsx
import { useEffect, useState } from "react";
import { getHealth } from "../lib/api";

export function Header({ threadId, onNewSession }: { threadId: string; onNewSession: () => void }) {
  const [healthy, setHealthy] = useState<boolean | null>(null);
  const [version, setVersion] = useState<string>("");

  useEffect(() => {
    let active = true;
    const check = async () => {
      try {
        const h = await getHealth();
        if (active) { setHealthy(h.status === "ok" || h.status === "healthy"); setVersion(h.version); }
      } catch {
        if (active) setHealthy(false);
      }
    };
    check();
    const id = setInterval(check, 10000);
    return () => { active = false; clearInterval(id); };
  }, []);

  const dot = healthy === null ? "bg-terminal-muted" : healthy ? "bg-terminal-accent" : "bg-terminal-danger";

  return (
    <header className="flex items-center justify-between border-b border-terminal-border bg-terminal-panel px-4 py-2">
      <div className="flex items-center gap-2">
        <span className={`h-2.5 w-2.5 rounded-full ${dot}`} />
        <span className="font-mono text-sm font-semibold">MIA · Dev Console</span>
        {version && <span className="font-mono text-xs text-terminal-muted">v{version}</span>}
      </div>
      <div className="flex items-center gap-3">
        <span className="font-mono text-xs text-terminal-muted">{threadId}</span>
        <button
          onClick={onNewSession}
          className="rounded border border-terminal-border px-2 py-1 font-mono text-xs text-terminal-text hover:border-terminal-accent"
        >
          New session
        </button>
      </div>
    </header>
  );
}
```

- [ ] **Step 4: Typecheck**

Run:
```bash
npx tsc -b
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/ChatPane.tsx frontend/src/components/ActivityRail.tsx frontend/src/components/Header.tsx
git commit -m "feat(frontend): ChatPane, ActivityRail, Header components"
```

---

## Task 8: VoicePanel (LiveKit)

**Files:**
- Create: `frontend/src/components/VoicePanel.tsx`

Ports the existing Streamlit LiveKit flow to React using `livekit-client`: fetch a token, connect, enable mic, attach + autoplay the agent's audio track. Unique room per connect (same rule as the current panel).

- [ ] **Step 1: Implement `VoicePanel.tsx`**

```tsx
import { useRef, useState } from "react";
import { Room, RoomEvent, type RemoteTrack } from "livekit-client";
import { getLiveKitToken } from "../lib/api";

export function VoicePanel() {
  const [status, setStatus] = useState("idle");
  const [log, setLog] = useState<string[]>([]);
  const roomRef = useRef<Room | null>(null);
  const addLog = (m: string) => setLog((p) => [...p, m]);

  async function connect() {
    try {
      setStatus("fetching token…");
      const identity = "user-" + Math.random().toString(36).slice(2, 8);
      const room = "mi-voice-" + Math.random().toString(36).slice(2, 10);
      const { token, url } = await getLiveKitToken(identity, room);
      addLog(`got token, connecting to ${url}`);

      const lkRoom = new Room({ adaptiveStream: true, dynacast: true });
      roomRef.current = lkRoom;
      lkRoom.on(RoomEvent.TrackSubscribed, (track: RemoteTrack) => {
        if (track.kind === "audio") {
          const el = track.attach() as HTMLAudioElement;
          el.autoplay = true;
          (el as HTMLMediaElement).muted = false;
          el.volume = 1.0;
          document.body.appendChild(el);
          el.play().then(() => addLog("agent audio playing")).catch((e) => addLog("audio error: " + e.message));
        }
      });
      lkRoom.on(RoomEvent.Disconnected, () => { setStatus("disconnected"); addLog("room disconnected"); });

      await lkRoom.connect(url, token);
      await lkRoom.localParticipant.setMicrophoneEnabled(true);
      setStatus("connected — speak now");
      addLog("mic enabled");
    } catch (err) {
      setStatus("error");
      addLog("error: " + (err as Error).message);
    }
  }

  async function disconnect() {
    await roomRef.current?.disconnect();
    roomRef.current = null;
    setStatus("idle");
  }

  const connected = status.startsWith("connected");

  return (
    <div className="border-t border-terminal-border bg-terminal-panel p-3">
      <div className="mb-2 flex items-center gap-2">
        <button
          onClick={connect}
          disabled={connected}
          className="rounded bg-terminal-accent px-3 py-1 text-xs font-semibold text-terminal-bg disabled:opacity-50"
        >
          🎤 Connect
        </button>
        <button
          onClick={disconnect}
          disabled={!connected}
          className="rounded border border-terminal-border px-3 py-1 text-xs text-terminal-text disabled:opacity-50"
        >
          Disconnect
        </button>
        <span className="font-mono text-xs text-terminal-muted">{status}</span>
      </div>
      <div className="max-h-24 overflow-y-auto rounded bg-terminal-bg p-2 font-mono text-[11px] text-terminal-muted">
        {log.map((l, i) => <div key={i}>{l}</div>)}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Typecheck**

Run:
```bash
npx tsc -b
```
Expected: no errors. (If `livekit-client` type names differ in the installed version, adjust the `RemoteTrack` import to the exported type; verify via `node -e "console.log(Object.keys(require('livekit-client')))"`.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/VoicePanel.tsx
git commit -m "feat(frontend): LiveKit VoicePanel"
```

---

## Task 9: Compose `App.tsx` + smoke test

**Files:**
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/App.test.tsx`

- [ ] **Step 1: Write the App smoke test (mocks fetch so no backend is needed)**

`frontend/src/App.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "./App";

describe("App", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ status: "ok", version: "1.2.3" }),
    }));
  });

  it("renders the header and chat input", async () => {
    render(<App />);
    expect(screen.getByText(/MIA · Dev Console/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /new session/i })).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/ask the agent/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run:
```bash
npm test -- App
```
Expected: FAIL — current `App.tsx` is the scaffold placeholder.

- [ ] **Step 3: Implement the full `App.tsx`**

```tsx
import { useState, type FormEvent } from "react";
import { Header } from "./components/Header";
import { ChatPane } from "./components/ChatPane";
import { ActivityRail } from "./components/ActivityRail";
import { ApprovalCard } from "./components/ApprovalCard";
import { VoicePanel } from "./components/VoicePanel";
import { useChatStream } from "./hooks/useChatStream";
import { newThreadId } from "./lib/api";

export default function App() {
  const [threadId, setThreadId] = useState(newThreadId);
  const [input, setInput] = useState("");
  const [voiceOpen, setVoiceOpen] = useState(false);
  const { messages, activity, streaming, pending, send, resolvePending, reset } =
    useChatStream(threadId);

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const q = input.trim();
    if (!q || streaming || pending) return;
    setInput("");
    void send(q);
  }

  function onNewSession() {
    setThreadId(newThreadId());
    reset();
  }

  return (
    <div className="flex h-full flex-col">
      <Header threadId={threadId} onNewSession={onNewSession} />
      <div className="flex min-h-0 flex-1">
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <ChatPane messages={messages} streaming={streaming} />
          </div>

          {pending && (
            <div className="px-4 pb-2">
              <ApprovalCard
                threadId={threadId}
                pending={pending}
                onResolved={(text, still) => resolvePending(text, still)}
              />
            </div>
          )}

          <form onSubmit={onSubmit} className="flex gap-2 border-t border-terminal-border p-3">
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={streaming || !!pending}
              placeholder="Ask the agent…"
              className="flex-1 rounded border border-terminal-border bg-terminal-bg px-3 py-2 font-mono text-sm outline-none focus:border-terminal-accent disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={streaming || !!pending}
              className="rounded bg-terminal-accent px-4 py-2 text-sm font-semibold text-terminal-bg disabled:opacity-50"
            >
              Send
            </button>
            <button
              type="button"
              onClick={() => setVoiceOpen((v) => !v)}
              className="rounded border border-terminal-border px-3 py-2 text-sm text-terminal-text"
            >
              🎤
            </button>
          </form>

          {voiceOpen && <VoicePanel />}
        </main>

        <ActivityRail activity={activity} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the App test to verify it passes**

Run:
```bash
npm test -- App
```
Expected: PASS.

- [ ] **Step 5: Run the full frontend test suite + build**

Run:
```bash
npm test && npm run build
```
Expected: all tests PASS; build succeeds.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/App.tsx frontend/src/App.test.tsx
git commit -m "feat(frontend): compose App shell with chat, HITL, activity, voice"
```

---

## Task 10: Docs — README + CLAUDE.md run recipe

**Files:**
- Create: `frontend/README.md`
- Modify: `CLAUDE.md` (Commands section)

- [ ] **Step 1: Create `frontend/README.md`**

```markdown
# MIA Dev Console (local-dev frontend)

A React + Vite + Tailwind dev tool for testing the Market Intelligence Agent:
chat streaming, human-in-the-loop approval, live agent activity, health/session
controls, and voice. Local development only — not part of the AWS deployment.

## Run

1. Start the backend (from `market-intelligence-agent/`):
   ```bash
   uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000 --reload
   ```
2. Start the frontend (from `market-intelligence-agent/frontend/`):
   ```bash
   npm install   # first time only
   npm run dev
   ```
3. Open http://localhost:5173

Voice also requires the LiveKit worker:
```bash
uv run python -m app.voice.worker dev
```

The Vite dev server proxies `/stream`, `/approve`, `/health`, `/livekit` to
`http://127.0.0.1:8000`. Override with `VITE_API_TARGET` if the backend runs elsewhere.

## Test
```bash
npm test
```
```

- [ ] **Step 2: Add a "React dev frontend" entry to `CLAUDE.md` Commands**

Insert after the Streamlit frontend command line in `CLAUDE.md`:
```markdown
# Run the React dev console (port 5173) — proxies to the backend on :8000
cd frontend && npm install && npm run dev
```

- [ ] **Step 3: Commit**

```bash
git add frontend/README.md CLAUDE.md
git commit -m "docs(frontend): dev console README + CLAUDE.md run recipe"
```

---

## Task 11: Manual verification + frontend-specialist visual pass

- [ ] **Step 1: Manual smoke against a live backend**

Start backend + frontend (see README). In the browser:
- Send "What is AMZN trading at?" → tokens stream into the assistant bubble; `rag`/`grader`/`generate`/`tools` appear in the Activity rail.
- Trigger a side-effect tool (e.g. "save a memory that my name is Yaniv") → ApprovalCard appears; Approve → action completes; Reject → cancelled message.
- Toggle 🎤 → Connect → confirm token fetch + mic enable (requires LiveKit worker).
- Health dot is green; New session mints a fresh `thread_id` and clears the view.

- [ ] **Step 2: frontend-specialist visual elevation**

Hand the working app to the frontend-specialist agent (or frontend-design skill) to elevate the visual design within the existing component contracts and Tailwind theme tokens — without changing the API/hook interfaces or breaking the Vitest tests. Re-run `npm test && npm run build` afterward.

- [ ] **Step 3: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to decide merge/PR.
```
