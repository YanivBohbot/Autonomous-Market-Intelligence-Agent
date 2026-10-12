# Supervisor as `create_agent` (Router pattern kept)

Date: 2026-10-12. Status: design approved in conversation, awaiting spec review.

## Goal

Make the multi-agent supervisor's routing LLM call a LangChain `create_agent` with official middleware, instead of a raw `ChatOpenAI.with_structured_output` call surrounded by hand-written plumbing.

The user's explicit preference is to use the official LangChain/LangGraph primitives and documented patterns rather than home-made equivalents, even if the code gets restructured.

## Non-goals

- **No change of orchestration pattern.** The Router pattern stays: specialists remain graph nodes that share `messages`, so Market Desk cards, the activity rail and reloaded history are unchanged. The Subagents pattern is out of scope.
- **No change to the specialists**, nor to the 5 deterministic routing rules.
- **No change to the routing prompt's content**, beyond how it is assembled.

## Decisions (agreed with the user)

1. **The router agent runs inside the `supervisor` node** with its own private state. It is not added to the graph as a subgraph node. If it were, its structured routing output would be written into the shared conversation and show up in Market Desk and in history.
2. **The credit-card guard becomes a `@before_agent(can_jump_to=["end"])` middleware on the router agent.** This is the decorator syntax from `docs.langchain.com/oss/python/langchain/guardrails`. It replaces the `input_guard` graph node. The user chose blocking over `PIIMiddleware(strategy="mask")`, which would silently mask the number and still answer.
3. **The 5 deterministic rules stay as Python in the `supervisor` node**, around the agent call. These are hop limit, forced finish, portfolio→email chaining, sticky "save it", and the FINISH-without-answer fallback. LangChain has no prebuilt equivalent, and the official Router example also keeps routing logic in graph code.
4. **Middleware deliberately not added to the router agent:**
   - `SummarizationMiddleware`: the router agent has no persistent history of its own.
   - `OpenAIModerationMiddleware`: every specialist already checks the input before its own model call, and a routing decision produces no user-facing text.
   - `PIIMiddleware`: cards are already blocked by the guard.

## Design

### Router agent (`app/agent/multi_agent/supervisor.py`)

```python
router_agent = create_agent(
    model=ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0,
                     metadata={"emit-messages": False, "emit-tool-calls": False}),
    tools=[],
    system_prompt=SUPERVISOR_ROUTING_PROMPT,
    response_format=RoutingDecision,           # read from result["structured_response"]
    state_schema=ClientContextState,
    middleware=[
        block_credit_cards,                    # @before_agent(can_jump_to=["end"])
        fresh_documents_prompt,                # existing @dynamic_prompt (ingested PDF list)
        client_context_routing_prompt,         # new @dynamic_prompt (active client sentence)
        context_editing(),                     # ContextEditingMiddleware + ClearOldTurnToolResults
        *([fallback] if (fallback := model_fallback()) else []),
        model_retry(),                         # ModelRetryMiddleware
    ],
    name="supervisor_router",
)
```

- `response_format=RoutingDecision` (Pydantic): LangChain picks `ProviderStrategy` (native structured output) for OpenAI.
- `emit-messages`/`emit-tool-calls: False` keeps AG-UI (Market Desk) from rendering the routing JSON. This is the same metadata the raw router uses today.
- The router agent is built once, at module level or lazily. It is exposed as a module attribute so tests can replace it with a fake that returns `{"structured_response": RoutingDecision(...)}`.

### Credit-card guard (`app/agent/guardrails/`)

`block_credit_cards`, written with the decorator syntax: `@before_agent(can_jump_to=["end"])`.

- It looks at the latest `HumanMessage`. If `contains_credit_card(...)` is true, it returns:
  - the same message masked (same id, so the `add_messages` reducer replaces it);
  - `AIMessage(SENSITIVE_DATA_WARNING)`;
  - `"jump_to": "end"`.
- Otherwise it returns `None`. Detection and masking reuse `detection.py`, which is built on LangChain's own `detect_credit_card`.
- `input_guard.py` and the `input_guard` graph node are deleted.

### Supervisor node flow

1. Rules 1-4 run before any LLM call, unchanged.
2. `result = router_agent.invoke({"messages": <copy of state messages>, "client_context": state.get("client_context")})`.
3. If `result` has no `structured_response`, the guard blocked. The node returns `Command(goto="finalize_turn", update={"messages": [masked HumanMessage, warning AIMessage]})`, taken from the agent's result messages.
4. Otherwise it reads `structured_response.next`, applies rule 5 (FINISH with no answer goes to `rag_agent`), and returns `Command(goto=next, update={...})` as today.

The node no longer builds the prompt by hand (placeholder substitution, client sentence) and no longer edits context manually. The `@dynamic_prompt` and `ContextEditingMiddleware` middleware do both.

### Graph (`app/agent/multi_agent/graph.py`)

- Remove the `input_guard` node. The edge becomes `record_question → supervisor`.
- `supervisor` declares `destinations` that include `finalize_turn`.
- Remove `retry_policy=RetryPolicy()` from `supervisor`. `ModelRetryMiddleware` covers transient OpenAI errors on the routing call.

### `/stream` (`app/api/routers/stream.py`)

- Tokens are streamed from nodes named `model`. The router agent also has a `model` node, so its JSON would be streamed as chat text. Fix: skip `messages`-mode tokens whose namespace is inside the `supervisor` node.
- `_STATIC_MESSAGE_NODES` loses `input_guard`. The card warning is now emitted from the `supervisor` node's update. Emit it only when that update carries the warning `AIMessage`, so ordinary routing updates emit nothing.

### Docs

Update `CLAUDE.md` (graph flow, guardrails, middleware list) and the `app/agent/guardrails/__init__.py` docstring. The `mask_credit_cards()` docstring in `middleware.py` currently mentions the graph-level `input_guard`.

## Testing

Unit tests, written TDD-first with no OpenAI call:

- **Guard:**
  - A card triggers `jump_to: "end"`, a masked message with the same id and the warning, and the model is never called (FakeToolModel `seen == []`).
  - With no card, the guard is a no-op.
- **Router agent:**
  - `structured_response` is returned.
  - The system prompt contains the live PDF manifest and the client sentence.
  - The model receives `[cleared]` for old-turn tool results, while the agent state stays intact.
- **Supervisor node:**
  - Every existing routing test is kept, with the fake moved from `_router` to `router_agent`. About 12 test files are affected.
  - A card-blocked turn goes to `finalize_turn` with the masked message and the warning.
- **Graph:**
  - No `input_guard` node, and no retry policy on `supervisor`.
  - End to end, the card path gives the warning, masks history, and calls no specialist.
- **`/stream`:** no token from inside `supervisor` is streamed, and the card warning is still emitted once.

## Acceptance (live)

1. The catalogue's core questions, run on a `qa_*` thread, route as before.
2. A card number is blocked with the same warning, and history holds the masked number.
3. In the LangSmith trace under `supervisor`, the router agent is visible with `ContextEditingMiddleware`, `ModelRetryMiddleware` and the guard. The routing call stays around 2k input tokens.
4. In Market Desk, no routing JSON appears in chat, and cards and the activity rail are unchanged.
5. The full backend and frontend test suites are green, then the backend is restarted. Commits stay local, with no push.
