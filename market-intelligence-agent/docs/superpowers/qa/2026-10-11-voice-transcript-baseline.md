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
