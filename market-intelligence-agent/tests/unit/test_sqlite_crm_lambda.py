import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import create_db as seed

HANDLER = Path(__file__).resolve().parents[3] / "prod" / "lambdas" / "sqlite_crm" / "handler.py"


@pytest.fixture(scope="module")
def handler(tmp_path_factory):
    os.environ.setdefault("DATA_S3_BUCKET", "test-bucket")
    os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
    spec = importlib.util.spec_from_file_location("sqlite_crm_handler", HANDLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    db = tmp_path_factory.mktemp("lambda") / "customers.db"
    seed.create_db(db)
    with patch.object(mod, "_ensure_db", return_value=str(db)):
        yield mod


def _call(mod, tool, args=None):
    ctx = SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": f"sqlite-crm___{tool}"}))
    return mod.lambda_handler(args or {}, ctx)


def test_list_tables(handler):
    out = _call(handler, "list_tables")
    assert out["ok"] is True
    assert {r["name"] for r in out["result"]} == {"companies", "clients", "transactions", "holdings", "watchlists"}


def test_describe_table(handler):
    out = _call(handler, "describe_table", {"table_name": "holdings"})
    assert out["ok"] is True
    assert [c["name"] for c in out["result"]] == ["client_id", "ticker", "shares", "avg_cost"]


def test_describe_unknown_table_lists_existing_tables(handler):
    out = _call(handler, "describe_table", {"table_name": "nope"})
    assert out["ok"] is False
    assert "unknown table" in out["error"] and "holdings" in out["error"]


def test_describe_table_rejects_injection(handler):
    out = _call(handler, "describe_table", {"table_name": 'clients"); DROP TABLE clients; --'})
    assert out["ok"] is False
    assert _call(handler, "read_query", {"query": "SELECT COUNT(*) AS n FROM clients"})["result"] == [{"n": 25}]


def test_read_query_still_works_and_stays_read_only(handler):
    assert _call(handler, "read_query", {"query": "SELECT COUNT(*) AS n FROM companies"})["result"] == [{"n": 14}]
    assert _call(handler, "read_query", {"query": "DELETE FROM clients"})["ok"] is False


def test_unknown_tool(handler):
    assert _call(handler, "write_query", {"query": "x"}) == {"ok": False, "error": "unknown tool: 'write_query'"}


def test_tool_schema_declares_the_three_tools():
    import json

    schema = json.loads((HANDLER.parent / "tool_schema.json").read_text(encoding="utf-8"))
    assert {t["name"] for t in schema} == {"read_query", "list_tables", "describe_table"}
