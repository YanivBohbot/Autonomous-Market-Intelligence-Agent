# test-driven-development

**Type:** Process (rigid — follow exactly)
**Plugin:** superpowers

## What it is
Write a failing test → watch it fail → write minimal code to pass → refactor. No
implementation code before the test exists.

## How we used it on this project
One of the two most-used skills across the whole history. Every plan task follows the
Step 1 "Write the failing test" → Step 2 "verify it fails" → Step 3 "implement" → Step 4
"verify it passes" pattern. Evidence in commits:

- `ada1cfc feat(browser): add BrowserSessionManager with lazy-start and unit test (T2)`
- `2c62ef0 test: add unit tests for grader node with mocked LLM`
- `9c04b32 fix: close SqliteSaver connection on shutdown, improve checkpointer test coverage`
- `e5c123f test(browser): QA cases 19 (snapshot) and 20 (HITL screenshot->brief)`

The 05-31 browser plan carries fully-written failing tests for every task
(`test_server_http.py`, `test_lifecycle.py`, `test_registry_http_entry.py`).
