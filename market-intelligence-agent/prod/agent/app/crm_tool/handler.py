"""CRM read-only SQL MCP server (Lambda-hosted via AgentCore Gateway).

Exposes a single tool `read_query(query: str) -> str` that runs SELECT-only SQL
against the bundled customers.db (read-only mode). Non-SELECT statements are
rejected at the handler level as defense in depth; Phase 5 will additionally
enforce this via Gateway Policy.

Tool name matches the dev project so the agent's system prompt and the
READ_ONLY_TOOLS allowlist work unchanged.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3

from mcp.server.fastmcp import FastMCP

app = FastMCP("crm")

# Resolve customers.db next to this handler. Lambda's working dir is /var/task
# and the CDK bundles the entire tool directory there, so a relative path works.
_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customers.db")

_SELECT_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


@app.tool()
def read_query(query: str) -> str:
    """Run a SELECT-only SQL query against the customers database. Returns JSON list of rows."""
    if not _SELECT_RE.match(query or ""):
        return json.dumps({"error": "Only SELECT queries permitted"})

    try:
        # Read-only + immutable URI flags prevent any writes regardless of query
        conn = sqlite3.connect(
            f"file:{_DB_PATH}?mode=ro&immutable=1",
            uri=True,
        )
        try:
            cursor = conn.cursor()
            cursor.execute(query)
            cols = [d[0] for d in (cursor.description or [])]
            rows = [dict(zip(cols, r)) for r in cursor.fetchall()]
            return json.dumps(rows, default=str)
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        return json.dumps({"error": f"read_query failed: {exc}"})
