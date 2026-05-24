"""Filesystem MCP Lambda — S3-backed read/list/write inside `mia-workspace`.

Replaces the @modelcontextprotocol/server-filesystem stdio server for production.
Same three tool names + argument shapes as the local dev path, so the agent code
in app/agent/tools/mcp_clients/filesystem_client.py is unchanged when
MCP_TRANSPORT=gateway.

Sandbox: all paths are interpreted as keys inside the single S3 bucket named by
WORKSPACE_S3_BUCKET. Path-traversal-style keys (`..`, leading `/`) are rejected.

Invoked by AgentCore Gateway with `{"tool": <name>, "args": {...}}`.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_s3 = boto3.client("s3")
_BUCKET = os.environ["WORKSPACE_S3_BUCKET"]


def _safe_key(path: str) -> str:
    if not path:
        raise ValueError("path is required")
    if path.startswith("/") or ".." in path.split("/"):
        raise ValueError(f"invalid path: {path!r}")
    return path.lstrip("./")


def _read_text_file(args: dict[str, Any]) -> str:
    key = _safe_key(args["path"])
    obj = _s3.get_object(Bucket=_BUCKET, Key=key)
    return obj["Body"].read().decode("utf-8")


def _list_directory(args: dict[str, Any]) -> list[dict[str, Any]]:
    raw = args.get("path", "").strip("/")
    prefix = f"{raw}/" if raw else ""
    out: list[dict[str, Any]] = []
    paginator = _s3.get_paginator("list_objects_v2")
    seen_prefixes: set[str] = set()
    for page in paginator.paginate(Bucket=_BUCKET, Prefix=prefix, Delimiter="/"):
        for entry in page.get("CommonPrefixes", []) or []:
            name = entry["Prefix"][len(prefix):].rstrip("/")
            if name and name not in seen_prefixes:
                out.append({"name": name, "type": "directory"})
                seen_prefixes.add(name)
        for entry in page.get("Contents", []) or []:
            name = entry["Key"][len(prefix):]
            if name and "/" not in name:
                out.append({
                    "name": name,
                    "type": "file",
                    "size": entry["Size"],
                    "lastModified": entry["LastModified"].isoformat(),
                })
    return out


def _write_file(args: dict[str, Any]) -> dict[str, Any]:
    key = _safe_key(args["path"])
    body = args["content"].encode("utf-8")
    # Bucket is configured with SSE-S3 default encryption; no explicit
    # ServerSideEncryption header needed — S3 applies it automatically.
    _s3.put_object(Bucket=_BUCKET, Key=key, Body=body)
    return {"path": key, "bytes": len(body)}


_DISPATCH = {
    "read_text_file": _read_text_file,
    "list_directory": _list_directory,
    "write_file": _write_file,
}


def lambda_handler(event, context):
    tool = event.get("tool")
    args = event.get("args") or {}
    logger.info("filesystem lambda invoked: tool=%s key=%s", tool, args.get("path"))
    fn = _DISPATCH.get(tool)
    if fn is None:
        return {"ok": False, "error": f"unknown tool: {tool!r}"}
    try:
        return {"ok": True, "result": fn(args)}
    except KeyError as e:
        return {"ok": False, "error": f"missing required arg: {e.args[0]}"}
    except ClientError as e:
        logger.exception("filesystem S3 op failed")
        return {"ok": False, "error": e.response.get("Error", {}).get("Message", str(e))}
    except Exception as e:
        logger.exception("filesystem tool %s failed", tool)
        return {"ok": False, "error": str(e)}
