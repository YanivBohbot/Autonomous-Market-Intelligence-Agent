# GitHub Pull Request CI — Design

## Goal

Extend the repository's existing GitHub Actions test workflow so every pull request targeting `master` validates both the FastAPI/Python backend and the React/Vite frontend before review. The workflow must remain validation-only: it must not deploy, require AWS credentials, or merge any branch.

## Current State

The repository already contains two root-level workflows:

- `.github/workflows/tests.yml` runs the Python test suite for pull requests targeting `master`.
- `.github/workflows/deploy.yml` tests and deploys the AgentCore production stack after eligible pushes to `master`.

This change will update only `tests.yml`. The production deployment workflow and its AWS permissions, secrets, and triggers remain unchanged.

## Trigger and Permissions

The CI workflow will run only for `pull_request` events whose base branch is `master`. It will not run on ordinary branch pushes and will not expose a manual deployment path.

The workflow will retain `contents: read` as its only explicit permission. It will use a pull-request-specific concurrency group with `cancel-in-progress: true`, so a new commit cancels an obsolete run for the same pull request.

## Job Design

Two independent jobs will run in parallel on GitHub-hosted Ubuntu runners.

### Backend

The backend job will:

1. Check out the repository.
2. Install `uv` with dependency caching enabled.
3. Install Python 3.12.
4. Run `uv sync --frozen` from `market-intelligence-agent/`.
5. Run `uv run pytest tests/ -v` from the same directory.

The frozen lockfile installation is mandatory. CI must fail rather than silently regenerate or relax `uv.lock`.

### Frontend

The frontend job will:

1. Check out the repository.
2. Install Node.js 20 with npm caching tied to `market-intelligence-agent/frontend/package-lock.json`.
3. Run `npm ci` from `market-intelligence-agent/frontend/`.
4. Run `npm test -- --run`.
5. Run `npm run build`.

`npm ci` is required so the committed lockfile defines the installed dependency tree. Tests and the production build are separate steps, making failures easy to identify in the GitHub interface.

## Failure and Security Behavior

Either job failing will make the pull request check fail. The jobs will not use environment secrets, contact AWS, start deployment infrastructure, or send e-mail. GitHub-hosted runners are ephemeral, and dependency caches will contain package-manager downloads rather than project secrets or generated application data.

The workflow will run both jobs for every pull request to `master`, including documentation-only changes. This keeps the required check predictable and avoids path-filter cases where GitHub can leave a required check pending or skipped.

## Validation

Before committing the workflow change:

- Validate the YAML structure locally.
- Run the complete backend suite using the same frozen `uv` installation contract.
- Run the complete frontend Vitest suite.
- Run the frontend production build.
- Review the final workflow diff to confirm that `.github/workflows/deploy.yml` is untouched.

After the branch is pushed and a pull request targeting `master` exists, GitHub must show two successful checks: backend tests and frontend tests/build. No merge will be performed without explicit user authorization.

## Out of Scope

- Deployments or changes to the production deployment workflow.
- Push-triggered CI on development branches.
- Automatic merging, releases, or package publication.
- Browser end-to-end tests, coverage thresholds, linting, or security scanning.
- Repository branch-protection configuration.
