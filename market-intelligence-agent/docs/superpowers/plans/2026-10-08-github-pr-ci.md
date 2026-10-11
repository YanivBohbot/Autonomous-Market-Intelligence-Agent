# GitHub Pull Request CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing pull-request workflow so every pull request targeting `master` validates the Python backend and the React/Vite frontend without deploying or using AWS secrets.

**Architecture:** Keep the existing root-level `.github/workflows/tests.yml` as the single CI entry point. Split validation into independent `backend` and `frontend` jobs that run in parallel on GitHub-hosted Ubuntu runners, retain read-only permissions and per-PR concurrency cancellation, and leave `.github/workflows/deploy.yml` unchanged.

**Tech Stack:** GitHub Actions, Ubuntu hosted runners, Python 3.12, uv, pytest, Node.js 20, npm, Vitest, TypeScript, Vite, PyYAML for local workflow validation.

**Spec:** `market-intelligence-agent/docs/superpowers/specs/2026-10-08-github-pr-ci-design.md`

## Global Constraints

- Trigger only on `pull_request` events whose base branch is `master`.
- Do not add a `push`, `workflow_dispatch`, schedule, deployment, release, or automatic-merge trigger.
- Keep workflow permissions at `contents: read` only.
- Do not use AWS credentials, repository secrets, environments, or deployment actions.
- Modify only `.github/workflows/tests.yml`; `.github/workflows/deploy.yml` must remain byte-for-byte unchanged.
- Run backend installation from `market-intelligence-agent/` with `uv sync --frozen` and Python 3.12.
- Run frontend installation from `market-intelligence-agent/frontend/` with `npm ci` and Node.js 20.
- Preserve per-pull-request concurrency with `cancel-in-progress: true`.
- Do not merge the branch into `master`.

## File Structure Map

- Modify: `.github/workflows/tests.yml` — defines the pull-request-only backend and frontend validation jobs.
- Verify only: `.github/workflows/deploy.yml` — production deployment workflow; its unchanged diff is a release-safety gate.
- Verify only: `market-intelligence-agent/uv.lock` — frozen backend dependency source.
- Verify only: `market-intelligence-agent/frontend/package-lock.json` — deterministic frontend dependency source and npm cache key.

## Review Focus

1. **Wrong trigger scope:** the validation script must assert that only `pull_request` targeting `master` exists and that `push` and `workflow_dispatch` are absent.
2. **Wrong working directory:** the validation script must pin backend commands to `market-intelligence-agent` and frontend commands to `market-intelligence-agent/frontend`.
3. **Incorrect cache source:** the validation script must pin npm caching to `market-intelligence-agent/frontend/package-lock.json`.
4. **Deployment or secret leakage:** the validation script must reject workflow text containing `secrets.`, AWS credential actions, or deploy commands.
5. **Non-deterministic installs or missing gates:** the validation script must require `uv sync --frozen`, `npm ci`, the complete pytest command, the complete Vitest command, and the Vite production build.

---

### Task 1: Add Parallel Backend and Frontend Pull-Request Validation

**Files:**
- Modify: `.github/workflows/tests.yml`
- Verify only: `.github/workflows/deploy.yml`

**Interfaces:**
- Consumes: `market-intelligence-agent/uv.lock`, `market-intelligence-agent/frontend/package-lock.json`, backend tests under `market-intelligence-agent/tests/`, and frontend scripts in `market-intelligence-agent/frontend/package.json`.
- Produces: GitHub checks named `Backend tests` and `Frontend tests and build` for every pull request targeting `master`.

- [ ] **Step 1: Run the workflow contract against the current file and verify RED**

Run from `market-intelligence-agent/`:

```powershell
$workflowCheck = @'
from pathlib import Path
import yaml

path = Path("../.github/workflows/tests.yml")
text = path.read_text(encoding="utf-8")
workflow = yaml.load(text, Loader=yaml.BaseLoader)

assert workflow["on"] == {"pull_request": {"branches": ["master"]}}
assert workflow["permissions"] == {"contents": "read"}
assert workflow["concurrency"]["cancel-in-progress"] == "true"
assert set(workflow["jobs"]) == {"backend", "frontend"}

backend = workflow["jobs"]["backend"]
frontend = workflow["jobs"]["frontend"]
assert backend["name"] == "Backend tests"
assert backend["defaults"]["run"]["working-directory"] == "market-intelligence-agent"
assert frontend["name"] == "Frontend tests and build"
assert frontend["defaults"]["run"]["working-directory"] == "market-intelligence-agent/frontend"

backend_runs = [step.get("run") for step in backend["steps"] if "run" in step]
frontend_runs = [step.get("run") for step in frontend["steps"] if "run" in step]
assert backend_runs == ["uv python install 3.12", "uv sync --frozen", "uv run pytest tests/ -v"]
assert frontend_runs == ["npm ci", "npm test -- --run", "npm run build"]

setup_node = next(step for step in frontend["steps"] if step.get("uses") == "actions/setup-node@v4")
assert setup_node["with"] == {
    "node-version": "20",
    "cache": "npm",
    "cache-dependency-path": "market-intelligence-agent/frontend/package-lock.json",
}

lower = text.lower()
for forbidden in ("secrets.", "configure-aws-credentials", "cdk deploy", "workflow_dispatch:", "push:"):
    assert forbidden not in lower, forbidden
'@
uv run python -c $workflowCheck
```

Expected: FAIL because the current workflow has a single `test` job and no frontend job.

- [ ] **Step 2: Replace the workflow with the minimal approved implementation**

Set `.github/workflows/tests.yml` to exactly:

```yaml
name: CI

# Validation only. Production deployment remains isolated in deploy.yml.
on:
  pull_request:
    branches: [master]

permissions:
  contents: read

concurrency:
  group: tests-${{ github.event.pull_request.number }}
  cancel-in-progress: true

jobs:
  backend:
    name: Backend tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: market-intelligence-agent
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
        with:
          enable-cache: true
      - name: Install Python 3.12
        run: uv python install 3.12
      - name: Install backend dependencies
        run: uv sync --frozen
      - name: Run backend tests
        run: uv run pytest tests/ -v

  frontend:
    name: Frontend tests and build
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: market-intelligence-agent/frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "20"
          cache: npm
          cache-dependency-path: market-intelligence-agent/frontend/package-lock.json
      - name: Install frontend dependencies
        run: npm ci
      - name: Run frontend tests
        run: npm test -- --run
      - name: Build frontend
        run: npm run build
```

- [ ] **Step 3: Rerun the workflow contract and verify GREEN**

Rerun the exact `$workflowCheck` command from Step 1.

Expected: PASS with exit code 0 and no output.

- [ ] **Step 4: Run the complete backend gate**

Run from `market-intelligence-agent/`:

```powershell
$env:UV_CACHE_DIR = Join-Path (Get-Location) ".uv-cache-ci"
uv sync --frozen
uv run pytest tests/ -v
```

Expected: dependency synchronization and every backend test PASS. If startup attempts external MCP, LLM, Pinecone, SES, or browser access, stop and isolate that boundary rather than weakening the CI command.

- [ ] **Step 5: Run the complete frontend gates**

Run from `market-intelligence-agent/frontend/`:

```powershell
npm ci
npm test -- --run --no-cache
npm run build
```

Expected: every Vitest test PASS and Vite completes a production build. The existing Rollup chunk-size advisory is acceptable; TypeScript errors, test failures, and unhandled runtime errors are not.

- [ ] **Step 6: Review isolation and repository cleanliness**

Run from the Git repository root:

```powershell
git diff --check -- .github/workflows/tests.yml
git diff --exit-code -- .github/workflows/deploy.yml
git status --short
```

Expected: no whitespace errors, no diff for `deploy.yml`, and only `.github/workflows/tests.yml` plus the four pre-existing Task 13 files appear outside already committed history. Do not stage `market-intelligence-agent/frontend/src/App.test.tsx`, `market-intelligence-agent/frontend/src/setupTests.ts`, `market-intelligence-agent/frontend/vite.config.ts`, or `market-intelligence-agent/frontend/src/viteProxy.test.ts`.

- [ ] **Step 7: Commit only the CI workflow**

Run from the Git repository root:

```powershell
git add -- .github/workflows/tests.yml
git diff --cached --check
git diff --cached --name-only
git commit -m "ci: validate backend and frontend pull requests"
```

Expected: the staged-name output contains only `.github/workflows/tests.yml` and the commit succeeds on `feat/product-ui-modernization`. Do not push, create a pull request, or merge until the user explicitly authorizes the corresponding GitHub action.

## Final Handoff

Report the workflow commit, exact backend and frontend test counts, production build result, and confirmation that `deploy.yml` is unchanged. Explain that the CI will run on GitHub when this branch is pushed and a pull request targeting `master` is opened or updated; no merge is part of this plan.
