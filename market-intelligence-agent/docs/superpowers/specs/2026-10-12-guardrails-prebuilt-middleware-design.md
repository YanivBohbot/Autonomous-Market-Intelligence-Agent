# Guardrails on LangChain Prebuilt Middleware

Date: 2026-10-12
Branch: `feat/product-ui-modernization` (PR #6)
References: LangChain docs "Guardrails" and "Prebuilt middleware" (langchain 1.4.2, langchain-openai with `OpenAIModerationMiddleware`).

## Problem

1. **Sensitive data reaches OpenAI before any guard runs.** The guard (`SensitiveDataGuard`) is a middleware inside each specialist (`create_agent`). The supervisor node runs first and calls OpenAI directly (`supervisor._router.invoke(...)` with every message), so a credit-card number reaches the LLM before any specialist blocks it. The supervisor is not a `create_agent`, so no middleware can attach to it.
2. **Custom code where prebuilt middleware exists.** `SensitiveDataGuard` is a custom `before_model` hook. The docs recommend `before_agent` for request-level checks, and prebuilt `PIIMiddleware` for PII. `guardrails/detection.py` calls `PIIMiddleware.before_model(..., runtime=None)` by hand, which its own comment admits is undocumented. `mask_credit_cards()` never fires on input, because the guard has already blocked the message.
3. **Missing guardrail families.** There is no output guardrail (PII in agent answers) and no model-based guardrail (harmful content).
4. **Tool reliability.** Flaky network tools (yfinance, MCP) fail once and go straight to `ToolErrorMiddleware`. Nothing caps runaway `web_search` or browser loops.

## Decisions (agreed with the user: "on fait les 4")

### 1. Graph-level input guard, before the supervisor

- **Placement.** A new node `input_guard` in `app/agent/multi_agent/graph.py`, wired `record_question → input_guard → (blocked ? finalize_turn : supervisor)`. The early exit goes through `finalize_turn`, so voice-tagging still runs.
- **Detection.** The official detector `langchain.agents.middleware.pii.detect_credit_card` (Luhn-validated), run on the latest `HumanMessage` text. Content-block lists are flattened to their text parts.
- **On a match.** The node returns `{"messages": [AIMessage(SENSITIVE_DATA_WARNING)]}` and the turn ends, so the supervisor and the specialists never run. **No LLM call happens for that turn.**
- **Emails are not blocked here.** The email, portfolio, memory and filesystem specialists need real addresses (unchanged policy). Emails are redacted per specialist instead (decision 2).
- **Detection module.** `guardrails/detection.py` is rewritten on the documented detectors `detect_credit_card` / `detect_email`, keeping the `contains_credit_card`, `contains_email` and `contains_sensitive_data` functions and `SENSITIVE_DATA_WARNING`.

### 2. Specialists use prebuilt guardrail middleware (replacing `SensitiveDataGuard`)

`SensitiveDataGuard` (`guardrails/middleware.py`) is removed. `base_middleware()` composes prebuilt middleware instead:

- `PIIMiddleware("credit_card", strategy="mask", apply_to_input=True, apply_to_output=True, apply_to_tool_results=True)`, on every specialist. This is defense in depth behind the input guard, and it also masks card numbers coming from tools or appearing in answers.
- `OpenAIModerationMiddleware(model="omni-moderation-latest", check_input=True, check_output=True, exit_behavior="end", violation_message=<project message>)`, on every specialist. This is the model-based guardrail. It is opt-out with the setting `MODERATION_ENABLED` (default `True`), so tests and offline runs can disable it.
- **Third-party specialists** (`rag`, `finance`, `browser`): the `redact_emails()` factory now returns `PIIMiddleware("email", strategy="redact", apply_to_input=True, apply_to_output=True)` (today it is input-only), and it replaces the old email *block*. Behavior change: an email address in a message to these specialists is now **redacted and the turn proceeds**. The docs' own example does exactly this, and these specialists never need an address.
- **Specialists that need addresses** (`email`, `portfolio`, `memory`, `filesystem`): no email PII middleware, unchanged. In particular `apply_to_output` must **never** redact emails on `email_agent`, because it would rewrite `send_email`'s `recipient` tool-call argument.
- The `check_email` parameter of `base_middleware()` goes away. Callers pass nothing, and the third-party specialists add `redact_emails()` (now input + output) as today.

### 3. Tool reliability middleware

- `ToolRetryMiddleware(max_retries=2, on_failure="error", tools=<read-only tool names of that specialist>)`, placed **inside** (after) `ToolErrorMiddleware` in the list, as the docs show. The exception reaches `ToolErrorMiddleware` only after the retries are used up.
  - **Never retry side-effect tools** (`send_email`, `write_file`, `save_memory`, `save_portfolio_report`). A retry could send an email twice. The list is derived from `READ_ONLY_TOOLS`, which finally gets a runtime use.
- `ToolCallLimitMiddleware(tool_name="web_search", run_limit=3)` on `rag_agent`, and `ToolCallLimitMiddleware(tool_name="browser_navigate", run_limit=5)` on `browser_agent`, with `exit_behavior="continue"`.

### 4. Streaming, docs, tests, live QA

- **`/stream`.** `_static_message_content` turns guard and moderation blocking messages into token events for the node names `input_guard` and `OpenAIModerationMiddleware.before_model`. These are static AIMessages, never model chunks, so without this the user would see a blank answer, which is the bug fixed in d3b7f9a.
- **Known limit (documented).** With `exit_behavior="end"`, an output-moderation violation in `after_model` leaves the flagged answer in state and appends the violation message after it; its tokens may already have streamed live. (`"replace"` was rejected: on input it rewrites the user message and still calls the model.) `PIIMiddleware(apply_to_output=True)` redacts the wire through LangChain's stream transformer. Whether our `/stream` path benefits from that is verified live and documented either way.
- **Live QA findings (2026-10-12).** `PIIMiddleware(apply_to_input=True)` writes the redacted messages back to the shared `messages` channel, so the user's own message is stored redacted in the thread history too (0 raw occurrences in `data/checkpoints.db`). Output redaction and output moderation run in `after_model`, after `/stream` has already forwarded the model's tokens: they fix state and history, not the live token stream.
- **Docs.** CLAUDE.md (multi-agent middleware bullet and guardrails), AGENTS.md if it is affected, and `docs/TOOLS.md` only if tool behavior is described. Edit; never delete.
- **Tests (TDD, targeted only; the user forbids full suites).**
  - `input_guard` blocks a card number and the supervisor is **never invoked**, asserted by patching `supervisor._router` and checking it was not called. A clean message passes through to the supervisor.
  - `detection.py` behaves the same on the existing cases and has no `before_model(..., None)` call left.
  - `base_middleware()` contains the expected prebuilt middleware in a safe order, and no `SensitiveDataGuard` remains.
  - The `email_agent` stack has no email PII middleware, the `rag`/`finance`/`browser` stacks do, and the moderation middleware is present when enabled and absent when disabled.
  - `ToolRetryMiddleware` covers only read-only tools (no side-effect tool name), and sits after `ToolErrorMiddleware`.
  - `/stream` emits a token for an `input_guard` block.
  - The existing guardrail tests are updated to the new behavior.
- **Live QA (backend restarted).**
  - A credit-card message streams the warning, and the server log shows **no supervisor or LLM call**.
  - A clearly harmful request is stopped by moderation, with the message shown.
  - "Send an email to Margaret Collins" still opens the approval card with the real address.
  - A RAG question still answers with citations.
  - A message with an email sent to the RAG agent is answered with the address redacted, not blocked.

## Final-review changes (2026-10-12)

- `input_guard` also masks the blocked message in place (same id, `****-****-****-1111`). Without this the raw number stayed in history and the supervisor router sent it to OpenAI on the next turn.
- Third-party email redaction is a small `RedactEmailsForModel` middleware (`wrap_model_call`, LangChain's `detect_email`) instead of `PIIMiddleware("email")`. The prebuilt middleware writes redacted messages back to the shared `messages` channel, so a later `email_agent` hop lost the recipient. The model copy is redacted; the stored conversation is not. Output is no longer redacted for these specialists, because their model never sees an address.

## Out of Scope

- `ContextEditingMiddleware`, `LLMToolSelectorMiddleware` and the other prebuilt middleware the user did not pick.
- Moving the supervisor onto `create_agent`.
- Changing which specialists may see real email addresses.
