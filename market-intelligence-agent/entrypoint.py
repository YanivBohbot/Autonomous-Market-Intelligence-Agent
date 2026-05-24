"""Container entrypoint for AgentCore Runtime.

Resolves Secrets Manager ARNs supplied via env vars into the plain values
the app's Settings class expects, then execs uvicorn on :8080. This keeps
secrets out of the CloudFormation template and out of image layers — they
live only in process memory after `os.environ[...] = ...`.

Expected env vars (set by MiaRuntimeStack):
- OPENAI_API_KEY_ARN, PINECONE_API_KEY_ARN, TAVILY_API_KEY_ARN, EMAIL_PASSWORD_ARN
"""

from __future__ import annotations

import logging
import os
import sys

import boto3

logger = logging.getLogger("entrypoint")
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))

_SECRET_MAP = {
    "OPENAI_API_KEY":   "OPENAI_API_KEY_ARN",
    "PINECONE_API_KEY": "PINECONE_API_KEY_ARN",
    "TAVILY_API_KEY":   "TAVILY_API_KEY_ARN",
    "EMAIL_PASSWORD":   "EMAIL_PASSWORD_ARN",
}


def _resolve_secrets() -> None:
    client = boto3.client("secretsmanager")
    for var, arn_var in _SECRET_MAP.items():
        if os.environ.get(var):
            continue  # already set (e.g. local dev)
        arn = os.environ.get(arn_var)
        if not arn:
            logger.warning("no ARN for %s (env %s missing); leaving unset", var, arn_var)
            continue
        try:
            value = client.get_secret_value(SecretId=arn)["SecretString"]
        except Exception:
            logger.exception("failed to fetch secret for %s from %s", var, arn)
            raise
        os.environ[var] = value
        logger.info("resolved %s from secrets manager", var)


def main() -> None:
    _resolve_secrets()
    import uvicorn  # late import — Settings instantiation depends on env being set
    uvicorn.run(
        "app.api.server:app",
        host="0.0.0.0",
        port=8080,
        log_level=os.environ.get("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    sys.exit(main())
