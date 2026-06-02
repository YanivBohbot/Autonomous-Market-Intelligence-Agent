# verification-before-completion

**Type:** Process (rigid — evidence before assertions)
**Plugin:** superpowers

## What it is
Before claiming work is done/fixed/passing, run the verification commands and confirm the
output. No success claims without evidence.

## How we used it on this project
The other most-used skill, and the source of a hard-won project lesson: **`status==completed`
is not a quality gate** — assertions must ground in real tool output (our
`feedback_smoke_vs_grounded_qa` memory, learned 2026-05-25). It produced the grounded-QA
harnesses:

- `prod/ci/probe_playground.py` — full HITL flow with fresh runtimeSessionId per call
- `prod/ci/qa_playground.py` — the 18/18-tool grounded QA suite
- `prod/ci/probe_browser_multistep.py` (planned) — asserts the *second* snapshot reflects the
  *second* URL, proving cross-call state, not just `status==completed`

Related standing rule: `test_before_push` — always verify locally before `git push`.
