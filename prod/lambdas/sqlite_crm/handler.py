"""SQLite CRM MCP Lambda — read-only read_query, list_tables, describe_table over customers.db.

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


def _connect() -> sqlite3.Connection:
    # Read-only mode is a second line of defense on top of IAM (GetObject only)
    # and the SELECT/WITH regex in _read_query.
    con = sqlite3.connect(f"file:{_ensure_db()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _table_names(con: sqlite3.Connection) -> list[str]:
    return [r["name"] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]


def _read_query(args: dict[str, Any]) -> list[dict[str, Any]]:
    sql = args["query"]
    if not _READ_ONLY_PATTERN.match(sql):
        raise ValueError("read_query only accepts SELECT or WITH statements")
    con = _connect()
    try:
        return [dict(r) for r in con.execute(sql).fetchall()]
    finally:
        con.close()


def _list_tables(args: dict[str, Any]) -> list[dict[str, Any]]:
    con = _connect()
    try:
        return [{"name": name} for name in _table_names(con)]
    finally:
        con.close()


def _describe_table(args: dict[str, Any]) -> list[dict[str, Any]]:
    name = args["table_name"]
    con = _connect()
    try:
        tables = _table_names(con)
        # Only names read back from sqlite_master reach the PRAGMA, so the
        # interpolation below cannot carry an injected statement.
        if name not in tables:
            raise ValueError(f"unknown table {name!r}; existing tables: {', '.join(tables)}")
        return [dict(r) for r in con.execute(f'PRAGMA table_info("{name}")').fetchall()]
    finally:
        con.close()


_DISPATCH = {
    "read_query": _read_query,
    "list_tables": _list_tables,
    "describe_table": _describe_table,
}


def _tool_name_from_context(context) -> str | None:
    try:
        raw = context.client_context.custom["bedrockAgentCoreToolName"]
    except (AttributeError, KeyError, TypeError):
        return None
    return raw.split("___", 1)[1] if "___" in raw else raw


def lambda_handler(event, context):
    tool = _tool_name_from_context(context)
    args = event if isinstance(event, dict) else {}
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
