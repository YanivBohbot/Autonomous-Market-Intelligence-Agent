# Research Voice: Visible Chat Transcript + Legacy UI Removal

Date: 2026-10-11
Branch: `feat/product-ui-modernization`
Supersedes: the "no visible transcript" decision in `2026-10-08-multi-agent-voice-research-design.md` (success criterion "neither user nor assistant voice transcripts are rendered in the Research chat", and the history presentation filter in "Thread and History Semantics").

## Goal

Make the React Research workspace the single voice-capable UI, and show the spoken conversation in its chat:

- While the user speaks, their words appear live, word by word, in a user bubble.
- When the agent answers, the answer text appears in the chat as one block, at roughly the moment the agent starts speaking it. The agent's voice still plays.
- Remove the Streamlit UI and the React `/classic` route, together with the code that only they used.

## Decisions (agreed with the user)

1. **Answer display = one block (option A).** The voice worker keeps running the graph to completion (`ainvoke`) before replying. Streaming the answer token by token was considered and rejected: it requires rewriting the worker around streaming for a cosmetic gain.
2. **Remove Streamlit and `/classic` (option A).** One UI only. `/stream` and `/approve` are kept: tests and the AgentCore deployment depend on them.
3. **Documentation files are updated, never deleted.** `CLAUDE.md`, `README.md` and `docs/VOICE.md` lose only the lines describing removed things.

## Success Criteria

- On `/research` with voice active, speaking makes a live caption bubble appear under the chat messages and grow as the transcript arrives.
- When the user's turn ends, the live caption disappears and the user's question appears as a normal user message (with a small mic badge).
- When the voice run finishes, the assistant's answer appears as a normal assistant message (mic badge) without any page reload.
- After a page reload, spoken turns are still in the chat history.
- Tool activity and the approval card keep working exactly as today.
- `app/ui/`, the `/classic` route and `GET /voice/{thread_id}/transcript` no longer exist. The full backend and frontend test suites pass.

## Architecture

The checkpoint stays the single source of truth for what is shown. No transcript text is added to `VoiceActivityStore`, so its privacy rule (no transcripts in presentation state) still holds.

### Live user caption (frontend only)

The browser already receives GPT-Live data-channel events. `useResearchVoice` handles two more event types in `channel.onmessage`:

- `session.input_transcript.delta`: appends `delta` to a `liveCaption` state.
- `session.delegation.created`: clears `liveCaption`, because the turn ended and the backend now runs it.

`liveCaption` is exposed through `ResearchVoiceContext`. `DeskView` renders a `LiveCaptionBubble` (user-styled, muted, with a mic icon and a typing indicator) below the chat messages while `liveCaption` is non-empty. It is cleared on cleanup and on disconnect.

### Committed turns (history refresh)

- **Backend:** `copilot.py` stops excluding voice messages. `_is_voice` is removed from `MarketDeskAgent._filter_orphan_tool_messages` and from `GET /copilot/market-desk/history`. The history items gain `"source": "voice" | "text"`, read from `additional_kwargs["source"]` and defaulting to `"text"`. The `source` tagging in `record_question` / `finalize_turn` is unchanged.
- **Frontend:** when a polled voice activity event with `kind === "run_finished"` arrives, `DeskView` refetches `/copilot/market-desk/history` and calls `agent.setMessages(history)`. This is the same mechanism already used on mount. It also refetches on `approval_required`, so the question asked before an approval pause is shown. Typing is already locked during voice mode, so replacing the message list cannot clobber an unsent text turn.
- **Mic badge:** chat messages whose history `source` is `voice` render a small mic badge. If CopilotKit's message model cannot carry the field, the badge is dropped. It is optional and must not block the feature.

### Data flow

```
mic ─► GPT-Live ─► data channel: input_transcript.delta ─► liveCaption bubble (live)
                └► sideband ─► worker ─► multi-agent graph ─► checkpoint (tagged source=voice)
                                   └► activity_store: run_finished ─► /voice/state poll
                                                                     └► DeskView refetch history ─► chat messages
                └► spoken answer (audio)
```

### Error handling

- If the history refetch fails, keep the current messages, show the existing non-blocking warning style ("Could not refresh the conversation"), and try again on the next `run_finished`. Voice keeps working.
- If the data channel never sends transcript deltas, no caption appears. Committed turns still arrive through the history refresh.

## Removals

Each item is deleted only once nothing outside the removed surface still uses it (checked with grep during implementation).

**Backend**
- `app/ui/` (Streamlit `app.py`, `voice_panel.py`) and the `streamlit` dependency in `pyproject.toml` / `uv.lock`.
- `app/voice/transcript_store.py`, `GET /voice/{thread_id}/transcript`, and `VoiceTranscriptResponse`.
- The classic branch of `app/voice/worker.py`: `_handle_delegation`, `GREETING`, the `surface="classic"` path and its `transcript_store` calls. Research becomes the only surface. The `surface` field of `GptLiveSessionRequest` is kept and validated as `research` only, so existing clients get a clear 422 instead of silent behavior.
- `app/voice/graph.py` / `build_voice_agent_app` and `app.state.voice_agent_app` in `server.py`, since only the classic worker and the transcript endpoint used them.
- `app/voice/hitl.py` is **kept**: `classify_verdict` is still used by `app/agent/multi_agent/supervisor.py`. Only the helpers that become unused (for example `is_interrupted` / `resume_with`, if so) are removed.
- The Streamlit service in `docker-compose.yml`.
- `app/agent/graph.py` (legacy single-agent graph) is **out of scope**: it may lose its last runtime caller once the Classic voice workflow is gone, but it also provides shared node helpers. Note it as a follow-up candidate in the plan; do not delete it in this change.

**Frontend**
- The `/classic` route and the `ClassicChat` component in `App.tsx`.
- `components/ChatPane.tsx`, `components/VoicePanel.tsx`, `components/ApprovalCard.tsx`, `components/ActivityRail.tsx`, and their tests, if only `ClassicChat` uses them.
- Hooks and API helpers in `lib/` or `hooks/` that only the classic chat used (`/stream` and `/approve` client code), if they become unused.

**Tests**
- Delete the tests of removed code: `test_voice_transcript.py`, `test_voice_graph_structure.py`, and the classic cases in `test_gptlive_session.py` and `test_server_wiring.py`.
- Update `test_workspace_screenshots.py` / `test_stream.py` only where they reference removed modules.

**Docs (update, not delete)**
- `CLAUDE.md`: remove the Streamlit run command, the Streamlit/voice-panel paragraphs, `/voice/{thread_id}/transcript`, `voice_agent_app`, and the classic-route mention. Describe voice as Research-only with a visible transcript.
- `README.md` and `docs/VOICE.md`: same edits.
- Add a "Superseded by `2026-10-11-research-voice-chat-transcript-design.md`" note at the top of the 2026-10-08 spec's transcript sections.

## Testing

**Backend (pytest)**
- History endpoint returns voice-tagged human and AI messages, with `source: "voice"`. Text messages get `source: "text"`.
- The AG-UI snapshot filter no longer drops voice messages, but still drops summarization messages.
- `GET /voice/{id}/transcript` returns 404. `POST /gptlive/session` with `surface="classic"` returns 422.
- Server startup no longer builds `voice_agent_app`.

**Frontend (Vitest)**
- `useResearchVoice`: transcript deltas accumulate into `liveCaption`, and `delegation.created`, disconnect and cleanup clear it.
- `DeskView`: the caption bubble renders only when non-empty. A `run_finished` event triggers one history refetch and `setMessages`. A failed refetch shows the warning and keeps the messages.
- `App`: `/classic` no longer renders the classic chat. It falls through to the app's default/unknown-route behavior.

**Live QA (once, at the end)**
Restart the backend, open `/research` in Chrome, enable voice, and ask "Which clients have more than 30 percent of their portfolio in one stock?". Verify the live caption, then the user message, then the assistant message plus audio, then the history after reload. Then run one email request and say "no" at the approval, to check that the approval still works and no email is sent.

## Regression Safety (requested by the user)

Nothing already built may break. Concretely:

1. **Baseline first.** Before any code change, run the full backend (`uv run pytest tests/ -q`) and frontend (`npm test -- --run`, `npm run build`) suites on the branch and record pass/fail counts and any pre-existing failures. A pre-existing failure is reported, not silently "fixed" as part of this work.
2. **After every task**, re-run the full suites, not only the new tests. The only allowed drop in test count is from deliberately deleted tests of removed code, listed by name in the commit message.
3. **Final gate.** The suites are green with counts equal to baseline minus the deleted tests plus the new ones, the frontend build is clean, and `grep` finds no remaining import of a removed module (`app.ui`, `transcript_store`, `app.voice.graph`, `VoicePanel`, `ChatPane`, `ClassicChat`).
4. **Code review** of the full diff (requesting-code-review) before the QA pass.

## Live QA Matrix (requested by the user)

Run once at the end against a freshly restarted backend and the React console in Chrome, on fresh thread ids (never reuse real client threads). Each check is grounded: it is verified against real tool output or the UI, not just "the request completed".

| # | Area | Check |
|---|---|---|
| 1 | Voice transcript (new) | Live caption grows while speaking, then becomes a user message. The answer appears as an assistant message plus audio. Both survive a reload. |
| 2 | Voice HITL | An email request by voice shows the approval card. Rejecting sends nothing and the chat records the cancellation. |
| 3 | Research text chat | A typed concentration question routes to `concentration_screen` and the answer names real clients from `customers.db`. |
| 4 | RAG | "What does Amazon's 2024 annual report say about AI?" answers with a `[Source: …, page N]` citation. |
| 5 | Market data | A ticker price question returns a live yfinance value. |
| 6 | Text HITL | A typed email or write_file request pauses for approval, and approving executes it (SES simulation or a workspace file). |
| 7 | Text and voice continuity | After a voice turn, the typed follow-up "summarize that" uses the voice context. |
| 8 | Briefing page | `/briefing` loads indices, movers, news and client alerts with no console errors. |
| 9 | Clients and Reports | The client list and a client workspace load, and a report generates. |
| 10 | Data page | The documents and clients lists load (no import performed). |
| 11 | Removed surfaces | `/classic` no longer shows the old chat, `GET /voice/x/transcript` returns 404, and nothing is listening on port 8080. |
| 12 | Backend API | `/health` is ok, and `/stream` plus `/approve` still complete an end-to-end run, since AgentCore depends on them. |

Any failure found in QA gets a root-cause fix plus a regression test, then that QA check is re-run. QA is not repeated just to chase normal LLM wording variance.

## Out of Scope

- Streaming the assistant answer token by token.
- Voice in client workspaces.
- Any change to `/stream`, `/approve` or the AgentCore deployment.
