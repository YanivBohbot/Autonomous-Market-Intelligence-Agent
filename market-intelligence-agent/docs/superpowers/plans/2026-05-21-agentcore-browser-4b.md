# Plan — AgentCore Browser Phase 4b

**Spec:** `docs/superpowers/specs/2026-05-21-agentcore-browser-design.md`
**Branch:** `feat/agentcore-prod`
**Last commit:** `9785067 docs(prod): mark Phase 4a done in deployment tracking doc`

## Working directory

All paths relative to `market-intelligence-agent/`. Commands run from `prod/agent/` unless noted.

## Steps

### 1 — Add dependencies to pyproject.toml

In `prod/agent/app/agent/pyproject.toml`, append to `dependencies`:
- `bedrock-agentcore>=0.1.0`
- `playwright>=1.50.0`

From `prod/agent/app/agent/`: `uv lock` to refresh the lockfile.

### 2 — Create `prod/agent/app/agent/app/agent/tools/browser.py`

Three `StructuredTool`s using `bedrock_agentcore.tools.browser_client.browser_session` + `playwright.async_api`. Pattern per tool:

```python
async def _navigate_async(url: str) -> dict:
    region = os.environ.get("AWS_REGION", "us-east-1")
    with browser_session(region) as client:
        ws_url, headers = client.generate_ws_headers()
        async with async_playwright() as pw:
            browser = await pw.chromium.connect_over_cdp(ws_url, headers=headers)
            try:
                page = browser.contexts[0].pages[0]
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                return {"title": await page.title(), "url": page.url, "status": "ok"}
            finally:
                await browser.close()
```

Use the same `_run_async` sync-bridge pattern from `mcp_clients/registry.py` (uvicorn already has a running loop, so naive `asyncio.run` will fail).

Screenshot tool uploads to S3:
```python
import boto3, uuid, os
bucket = os.environ["SCREENSHOT_BUCKET"]
key = f"screenshots/{uuid.uuid4()}.png"
s3 = boto3.client("s3")
png = await page.screenshot(full_page=False)
s3.put_object(Bucket=bucket, Key=key, Body=png, ContentType="image/png")
url = s3.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
return {"title": ..., "url": ..., "screenshot_url": url}
```

Tool names match dev exactly: `browser_navigate`, `browser_snapshot`, `browser_take_screenshot`.

### 3 — Gate imports in `tools/__init__.py`

After the Phase 4a Gateway block, add:

```python
if os.environ.get("BROWSER_ENABLED", "").lower() in ("1", "true", "yes"):
    try:
        from app.agent.tools.browser import (
            browser_navigate_tool,
            browser_snapshot_tool,
            browser_screenshot_tool,
        )
        TOOLS.extend([browser_navigate_tool, browser_snapshot_tool, browser_screenshot_tool])
        logger.info("[tools] Browser tools enabled (AgentCore Browser)")
    except Exception as exc:
        logger.warning("[tools] Failed to import browser tools (%r) — skipping", exc)
else:
    logger.info("[tools] BROWSER_ENABLED unset — browser tools skipped")
```

Add browser names to `READ_ONLY_TOOLS`.

### 4 — CDK: S3 bucket + IAM + env vars

In `prod/agent/agentcore/cdk/lib/cdk-stack.ts`, after the checkpoint table block:

```ts
const screenshotBucket = new s3.Bucket(this, 'ScreenshotBucket', {
  bucketName: `${spec.name}-screenshots-${this.account}-${this.region}`,
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
  encryption: s3.BucketEncryption.S3_MANAGED,
  removalPolicy: RemovalPolicy.RETAIN,
  lifecycleRules: [{ expiration: cdk.Duration.days(30) }],
});

for (const [, env] of this.application.environments) {
  env.runtime.addEnvironmentVariable('SCREENSHOT_BUCKET', screenshotBucket.bucketName);
  env.runtime.addEnvironmentVariable('BROWSER_ENABLED', 'true');
  screenshotBucket.grantReadWrite(env.runtime.role);  // or addToPolicy with PutObject/GetObject only
  env.runtime.addToPolicy(new iam.PolicyStatement({
    effect: iam.Effect.ALLOW,
    actions: [
      'bedrock-agentcore:StartBrowserSession',
      'bedrock-agentcore:StopBrowserSession',
      'bedrock-agentcore:GetBrowserSession',
      'bedrock-agentcore:ConnectBrowserAutomationStream',
    ],
    resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:browser/*`],
  }));
}
```

Add CfnOutput for the bucket name.

Verify the AgentCoreRuntime L3 construct exposes `.role` or equivalent — if not, fall back to a manual `iam.Role.fromRoleArn(env.runtime.executionRoleArn)`.

### 5 — Validate

From `prod/agent/agentcore/cdk/`: `npx tsc --noEmit`.
From `prod/agent/`: `agentcore validate`.

### 6 — README

Append "Browser tool" subsection: enabled via `BROWSER_ENABLED=true`, screenshots land in `$SCREENSHOT_BUCKET`, pre-signed URLs expire in 1h, lifecycle deletes objects after 30 days.

### 7 — Commit + push + tracking docs

1. Stage: new browser.py, modified __init__.py, pyproject.toml, uv.lock, cdk-stack.ts, README.md.
2. Commit: `feat(prod/agent): Phase 4b — AgentCore Browser + S3 screenshots`.
3. Append Phase 4b entry to `docs/AGENTCORE_DEPLOYMENT.md`.
4. Update memory file `project_agentcore_prod_inflight.md`.
5. Commit docs + push.

## What "done" looks like

- tsc + agentcore validate clean.
- New: `tools/browser.py`, spec + plan.
- Modified: `tools/__init__.py`, `pyproject.toml`, `uv.lock`, `cdk-stack.ts`, `README.md`, `AGENTCORE_DEPLOYMENT.md`.
- 2 commits pushed.

## NOT in scope

- Per-thread session caching.
- Stateful flows (login → action).
- Custom browser provisioning.
- Smoke tests (deferred — real browser only post-deploy).
