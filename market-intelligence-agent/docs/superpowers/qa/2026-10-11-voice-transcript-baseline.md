# Baseline — 2026-10-11 (before voice transcript work)

Branch: feat/product-ui-modernization @ eb9f267

| Suite | Passed | Failed | Skipped | Notes |
|---|---|---|---|---|
| Backend pytest (plain `uv run pytest tests/ -q`) | 0 | 0 | 0 | Aborted at collection: 14 modules error (`ModuleNotFoundError` on `anthropic.types.beta...self_hosted_resources_unsupported_deployment_paused_reason_error`). No tests executed. |
| Backend pytest (`--continue-on-collection-errors`) | 447 | 39 | 0 | 26 errors (setup errors in 15 files, same import root cause). 65 failing/erroring tests, 64 with the anthropic `ModuleNotFoundError`, 49 with `ImportError: Initializing ChatAnthropic requires the langchain-anthropic package`, 1 unrelated assertion (`test_router_output_is_hidden_from_ag_ui_streams`). |
| Frontend vitest (full run) | 275 | 3 | – | 48 files (2 failed files). Failing: `src/desk/ApprovalPanel.test.tsx` (2 tests, 5-6s timeouts), `src/reports/ReportWorkspace.test.tsx` (1 test, 5s timeout). Re-run in isolation: 31/31 pass, so load-dependent flakiness. |
| Frontend build (`npm run build`) | ok | | | Exit 0. Only a chunk-size warning (>500 kB). |

Pre-existing failures are NOT fixed as part of this work; they are reported.

Root cause of backend failures (environmental, not code): the worktree path is deep enough that `.venv/Lib/site-packages/anthropic/types/beta/beta_managed_agents_self_hosted_resources_unsupported_deployment_paused_reason_error.py` (260 chars) is not visible to Python on Windows (`os.path.exists` returns False). Windows `LongPathsEnabled` = 0.

## After (targeted gate)

Full-suite runs (`uv run pytest tests/`, `npm test`) were excluded by the controller. This gate runs every test file changed on the branch since `bb444f7` plus every unit test importing a touched voice/copilot/stream/approve module, at HEAD `99ba970`.

| Command | Passed | Failed | Notes |
|---|---|---|---|
| `UV_PROJECT_ENVIRONMENT=F:/venvs/mia-ui uv run pytest` on 15 files: `test_agentcore_contract`, `test_health`, `test_approve`, `test_copilot_endpoint`, `test_copilot_uploads`, `test_copilot_wiring`, `test_hitl_interrupt`, `test_multi_agent_hitl`, `test_research_voice_api`, `test_research_voice_runtime`, `test_server_wiring`, `test_stream`, `test_voice_activity_store`, `test_voice_hitl_classify`, `test_workspace_screenshots` | 100 | 0 | Collection clean (no anthropic `ModuleNotFoundError` in this venv). |
| `npx vitest run src/App.test.tsx src/layout/ src/desk/ src/voice/ src/lib/ src/briefing/ src/clients/ src/reports/ src/data/` | 278 (47 files) | 0 | Includes `ApprovalPanel` and `ReportWorkspace`, which were the load-dependent timeouts in the baseline; both passed in this run. |
| `npm run build` | ok | | Exit 0. Chunk-size warning only. |
| Dead-import grep (`app\.ui\|transcript_store\|app\.voice\.graph\|voice_agent_app` in `app`, `tests`) | 0 matches | | Clean. |
| Dead-reference grep (`VoicePanel\|ChatPane\|ClassicChat\|useChatStream` in `frontend/src`) | 0 matches | | Clean. |

No targeted test failed, so no pre-existing-vs-new classification was needed.

Deleted test files (`git diff --diff-filter=D bb444f7..HEAD -- tests/`): `tests/unit/test_gptlive_session.py`, `tests/unit/test_voice_graph_structure.py`, `tests/unit/test_voice_transcript.py`.

Deleted or removed test functions (from `git diff bb444f7..HEAD -- tests/`, removed-line `def test_` entries):
- `test_copilot_endpoint.py`: `test_history_and_snapshots_hide_voice_turns_but_checkpoint_retains_them`
- `test_gptlive_session.py` (file deleted): `test_create_session_forwards_caller_supplied_thread_id`, `test_create_session_falls_back_to_voice_prefixed_thread_id_when_absent`
- `test_research_voice_api.py`: `test_omitted_surface_preserves_classic_worker_contract`
- `test_voice_graph_structure.py` (file deleted): `test_voice_graph_compiles`, `test_voice_graph_has_no_init_node`
- `test_voice_transcript.py` (file deleted): `test_append_and_get_after_returns_only_newer_entries`, `test_get_after_unknown_thread_returns_empty`, `test_classic_transcript_contract_remains_available`, `test_transcript_endpoint_returns_new_messages_and_advances_cursor`, `test_transcript_endpoint_reports_paused_state`, `test_transcript_endpoint_reports_not_paused`

Frontend files deleted in the same range (not in the targeted run): `ApprovalCard.test.tsx` and `ApprovalCard.tsx`, `ActivityRail.tsx`, `ChatPane.tsx`, `VoicePanel.tsx`, `useChatStream.ts`.
