"""SQLite CRM MCP Lambda — read-only `read_query` over customers.db.

Mirrors the mcp-server-sqlite read_query tool that runs locally as a stdio
subprocess in dev. In production the DB file lives in the `mia-data` bucket
under key `customers.db`. We download it to `/tmp` on cold start (it's tiny —
~200 KB) and reuse the same on-disk copy across warm invocations.

This Lambda is intentionally read-only: write/insert/update queries are
rejected before we open a connection. Defense-in-depth on top of IAM (the
execution role only has `s3:GetObject` on the data bucket).
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

_s3 = boto3.client("s3")
_BUCKET = os.environ["DATA_S3_BUCKET"]
_DB_KEY = os.environ.get("CRM_DB_KEY", "customers.db")
_LOCAL_PATH = "/tmp/customers.db"

_READ_ONLY_PATTERN = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _ensure_db() -> str:
    if not os.path.exists(_LOCAL_PATH):
        logger.info("downloading %s/%s → %s", _BUCKET, _DB_KEY, _LOCAL_PATH)
        _s3.download_file(_BUCKET, _DB_KEY, _LOCAL_PATH)
    return _LOCAL_PATH


def _read_query(args: dict[str, Any]) -> list[dict[str, Any]]:
    sql = args["query"]
    if not _READ_ONLY_PATTERN.match(sql):
        raise ValueError("read_query only accepts SELECT or WITH statements")
    path = _ensure_db()
    # Open the DB in read-only mode as a second line of defense against any
    # statement that slipped past the regex (PRAGMA, ATTACH, etc.).
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute(sql)
        return [dict(r) for r in cur.fetchall()]
    finally:
        con.close()


_DISPATCH = {
    "read_query": _read_query,
}


def lambda_handler(event, context):
    tool = event.get("tool")
    args = event.get("args") or {}
    logger.info("sqlite-crm lambda invoked: tool=%s", tool)
    fn = _DISPATCH.get(tool)
    if fn is None:
        return {"ok": False, "error": f"unknown tool: {tool!r}"}
    try:
        return {"ok": True, "result": fn(args)}
    except KeyError as e:
        return {"ok": False, "error": f"missing required arg: {e.args[0]}"}
    except Exception as e:
        logger.exception("sqlite-crm tool %s failed", tool)
        return {"ok": False, "error": str(e)}
