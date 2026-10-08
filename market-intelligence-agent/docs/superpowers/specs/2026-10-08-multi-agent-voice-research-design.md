# Multi-Agent Voice Mode for Research — Design

**Status:** Written specification approved by the user on 2026-10-08; implementation plans prepared for review.

## Goal

Integrate the application's existing continuous GPT-Live voice experience into the modern Research workspace and route spoken requests through the same multi-agent supervisor used by typed Research requests. Voice and text must share agent context, guardrails, tools, checkpoints, and Human-in-the-Loop (HITL) behavior without displaying voice transcripts in the visual chat.

## Success Criteria

- Research offers a microphone control that starts the existing continuous voice experience.
- Voice and text use the same Research `thread_id` and the same compiled multi-agent graph.
- Input is mutually exclusive: while voice mode is active, the user cannot type or send chat messages.
- The composer becomes an animated English-language voice bar with `Listening…`, `Analyzing…`, `Speaking…`, and `Approval required` states.
- The Intelligence rail shows the active specialist, tool calls, durations, approvals, completion, and errors for spoken turns.
- Spoken turns remain available as private conversation context after voice mode ends, but neither user nor assistant voice transcripts are rendered in the Research chat.
- Sensitive actions can be approved or rejected verbally or from the visible approval card, with exactly one decision applied.
- Ending or losing a voice session always releases microphone resources and restores text input.

## Scope

Voice mode is added only to the main `/research` workspace in this phase. Client-specific chat workspaces remain text-only. The existing `/classic` route and its voice behavior are preserved for compatibility; removing or redesigning that route is not part of this work.

This feature reuses the existing WebRTC, GPT-Live session negotiation, sideband delegation worker, audio output, and spoken approval classifier. It does not introduce Pipecat, replace GPT-Live, create a second voice orchestrator, or turn voice into push-to-talk dictation. Tablet and mobile layouts remain outside the current product scope.

All new interface text is English.

## User Experience

Research initially behaves exactly as it does today. The microphone control is disabled while a typed request or unresolved approval is active. Starting voice mode immediately replaces the composer with a transitional `Connecting…` state, requests microphone permission, and establishes the WebRTC session. Failure restores the composer; success advances to `Listening…`.

While connected, the composer is replaced by the approved compact voice bar:

- `Listening…`: an animated waveform responds to microphone activity.
- `Analyzing…`: a restrained processing animation is shown while the graph runs.
- `Speaking…`: the animation indicates that the assistant is producing audio.
- `Approval required`: the bar says `Say Approve or Reject · or use the card`.

The bar always includes `Voice mode · Text input locked` and an `End voice mode` action. Specialist names and tool detail do not appear in this bar; they remain in the existing Intelligence rail.

The assistant's response is spoken but not inserted into the chat. After voice mode ends, the user may type a contextual follow-up such as `Generate the report` without restating what was discussed by voice.

## Shared Multi-Agent Architecture

The Market Desk multi-agent graph becomes a shared application dependency rather than a graph instance owned only by the Copilot/AG-UI route. FastAPI compiles it once during application lifespan and exposes the same instance to:

1. the existing Research text transport; and
2. the voice sideband worker.

The voice worker no longer invokes the single-agent `app.voice.graph` for Research sessions. Each completed spoken turn is submitted to the shared supervisor using the exact Research `thread_id` already passed to `DeskView`. The supervisor selects the existing RAG, finance, portfolio, browser, email, filesystem, or memory specialist. Existing middleware, call limits, tool error conversion, recipient checks, checkpointing, and HITL rules therefore apply equally to text and voice.

The voice transport remains deliberately separate from orchestration. GPT-Live handles microphone input, voice activity detection, and audio output; it does not become a second supervisor and does not select business tools directly.

## Frontend Components

`DeskView` gains an explicit `voiceEnabled` capability. The `/research` route passes it as enabled; `ClientWorkspace` leaves it disabled. This makes page scope testable and avoids inferring behavior from URLs inside reusable components.

The voice UI is split into focused units:

- `ResearchVoiceController`: owns WebRTC lifecycle, microphone tracks, server session creation, state transitions, activity polling, and cleanup.
- `VoiceModeBar`: presentation-only rendering of the four approved states and the end-session action.
- `ResearchVoiceApproval`: adapts a voice-originated pending action to the existing approval-card presentation.
- A small Research input-state contract coordinates the CopilotChat composer and voice controller so only one input mode can be active.

The controller reports voice status to the existing Intelligence presentation rather than creating a separate activity panel.

## Thread and History Semantics

Typed and spoken turns share one checkpoint thread. Messages created during a voice run are tagged with `source=voice` at the persistence boundary. They remain in LangGraph state for subsequent reasoning and memory continuity.

The Research history response filters voice-tagged human and assistant messages before returning visual chat history. This is a presentation filter only: it must not delete or fork checkpoint state. Tool activity and approval events may still appear in Intelligence because they are operational status, not transcript content.

The server prevents concurrent graph turns for the same thread. A voice session cannot start while a typed turn is running, and a typed turn cannot start while voice owns the thread. The frontend provides immediate feedback, while the backend enforces the rule to cover multiple tabs and race conditions.

## HTTP Contracts

The existing `POST /gptlive/session` request keeps `sdp` and `thread_id` and gains a `surface` discriminator. Research sends `surface: "research"`; omitted values preserve Classic compatibility. The server returns `409` when the thread is owned by another active turn and otherwise keeps the existing GPT-Live SDP response contract.

Research reads `GET /voice/{thread_id}/state?after=<sequence>`. The response contains the current voice state, incremental normalized activity events, and an optional pending approval with its stable interrupt identifier. It contains no transcript messages.

Visual voice approvals use `POST /voice/{thread_id}/decision` with the interrupt identifier and a HumanInTheLoop-compatible decision. The spoken decision path calls the same coordinator internally rather than making a separate HTTP request. Stale or repeated interrupt identifiers return the already-applied result without resuming the graph again.

The existing `GET /voice/{thread_id}/transcript` endpoint remains available for Classic/Streamlit compatibility. Research does not call it. Research's normal history endpoint applies the voice-message presentation filter described above.

## Activity Transport

The sideband worker streams normalized lifecycle events into a bounded, per-thread voice activity store. Events contain sequence number, run identifier, node or specialist name, tool name when applicable, status, duration, and safe error text. They never contain raw microphone audio, full user transcripts, credentials, or binary tool output.

While voice mode is active, `ResearchVoiceController` reads incremental activity through a dedicated voice-state endpoint and feeds those events into the same timeline model used by `DeskActivityRail`. The endpoint also returns the current voice state and any pending approval. Activity is ephemeral UI state; the LangGraph checkpoint remains the durable source of conversational truth.

## HITL Coordination

A shared approval coordinator resolves pending multi-agent interrupts for both transports. Every pending action has a stable interrupt identifier. The coordinator accepts:

- spoken `Approve` or `Reject` decisions classified by the existing voice logic; or
- visual `approve`, `reject`, or supported `edit` decisions from the approval card.

The first valid decision for an interrupt wins and atomically resumes the graph. Repeated or late decisions return the already-applied outcome and never execute the tool twice. Editing remains a visual-card capability; voice keeps the established approve/reject interaction.

When approval is required, GPT-Live asks for the decision aloud and the same action is shown on screen. The existing email report selector remains available in the visual card. If the user chooses a report or edits fields, the visual edit decision is submitted through the shared coordinator.

## Session Lifecycle and Failure Handling

The browser creates the WebRTC event channel before sending its SDP offer. The server negotiates the session without exposing the OpenAI API key. Ending the call sends the normal session-close event and waits briefly for finalization before forced cleanup.

Cleanup is idempotent and always stops microphone tracks, closes the data channel and peer connection, clears timers, releases the per-thread voice ownership, and restores the composer.

- Microphone permission denied: show `Microphone access is required`; do not enter voice mode.
- Session negotiation failure: show a concise connection error and keep text available.
- Connection loss: show `Voice session disconnected`, clean up, and restore text input.
- Agent or read-only tool failure: speak a short safe failure, record it in Intelligence, and return to listening when the session remains healthy.
- User ends during analysis: cancel the active voice response on a best-effort basis and ignore late audio. A read-only operation already running may finish server-side, but no approval-gated side effect may execute without a decision.
- Unresolved approval on disconnect: keep the graph paused. The visible card remains the recovery path after text input is restored.

## Security and Privacy

- OpenAI credentials remain server-side.
- Session creation validates non-empty, size-bounded SDP input and allowed browser origins.
- Existing recipient, generated-report, filesystem, and memory guardrails remain authoritative.
- Voice activity payloads expose only UI-safe metadata.
- Raw audio is not persisted by this feature.
- Voice transcripts are retained only inside the existing checkpoint context required for conversational continuity and are excluded from visual history responses.
- Public deployment still requires authenticated, server-owned thread access; voice integration must not weaken that release gate.

## Verification

Backend tests cover shared graph construction, voice routing to every specialist, same-thread context continuity, voice-history filtering, per-thread turn exclusion, activity normalization, spoken and visual HITL decisions, duplicate-decision idempotency, disconnect behavior, and unresolved approvals.

Frontend tests cover Research-only availability, microphone permission states, composer replacement, all English status labels, input locking, cleanup, activity-rail updates, approval-card rendering, and the absence of transcript messages.

Integration tests use mocked WebRTC and model boundaries. Final manual QA uses a real microphone and GPT-Live session to verify one read-only finance request, one multi-step portfolio request, one spoken approval, one visual approval, interruption recovery, and a typed contextual follow-up after voice mode ends.

The complete backend suite, frontend suite, and production frontend build must pass before handoff. The application is restarted from the feature worktree so the user can test `/research` locally.

## Delivery Dependency

Implementation must build on the approved multi-agent cutover rather than adapting the old single-agent voice graph twice. If the cutover branch cannot be applied cleanly to the modernized UI branch, the implementation plan must first isolate and port the shared graph/stream/HITL changes, validate them, and then add the Research voice interface. No branch is merged as part of specification or planning work.
