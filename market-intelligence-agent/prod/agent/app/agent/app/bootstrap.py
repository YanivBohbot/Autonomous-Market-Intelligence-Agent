"""Boot-time secret loader.

Runs at module import — *before* any code that reads `os.environ` for app
secrets (in particular `app.core.config.Settings`, which is instantiated at
its own module load). The function fetches a JSON-encoded secret from AWS
Secrets Manager and copies each key into `os.environ`, after which
pydantic-settings sees the values as if they had come from `.env`.

In local dev, `API_KEYS_SECRET_ARN` is unset, this is a no-op, and the
existing `.env.local` continues to provide the keys.

Import order in `main.py`:
    import app.bootstrap              # <- this module; mutates os.environ
    from app.agent.graph import ...   # <- transitively imports core.config

Never log secret VALUES — only key names and counts.
"""

from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)


def load_secrets() -> None:
    arn = os.environ.get("API_KEYS_SECRET_ARN")
    if not arn:
        logger.info("[bootstrap] API_KEYS_SECRET_ARN unset — skipping secret fetch")
        return

    # boto3 is already a transitive of bedrock-agentcore; import lazily so
    # local dev (where this branch never runs) doesn't pay the import cost.
    import boto3

    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("secretsmanager", region_name=region)

    try:
        response = client.get_secret_value(SecretId=arn)
    except Exception as exc:  # noqa: BLE001
        # Fail loud — if the secret can't be fetched, the agent has no API keys
        # and every downstream call will fail anyway. Crash fast at boot rather
        # than 30s later inside a tool call.
        logger.error("[bootstrap] failed to fetch secret %s: %r", arn, exc)
        raise

    payload = response.get("SecretString")
    if not payload:
        raise RuntimeError(f"[bootstrap] secret {arn} has no SecretString (binary not supported)")

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"[bootstrap] secret {arn} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise RuntimeError(f"[bootstrap] secret {arn} JSON must be an object, got {type(data).__name__}")

    populated = 0
    for key, value in data.items():
        if not isinstance(value, str):
            logger.warning("[bootstrap] secret key %r has non-string value, coercing via str()", key)
            value = str(value)
        # Don't overwrite values that were already in env — lets ops override
        # individual keys via runtime env var injection without re-saving the
        # secret.
        if key in os.environ:
            continue
        os.environ[key] = value
        populated += 1

    logger.info("[bootstrap] loaded %d keys from %s", populated, arn)


# Run at import time so it executes before any downstream module reads env.
load_secrets()
