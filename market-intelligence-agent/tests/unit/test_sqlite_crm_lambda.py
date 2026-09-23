import importlib.util
import os
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import create_db as seed

HANDLER = Path(__file__).resolve().parents[3] / "prod" / "lambdas" / "sqlite_crm" / "handler.py"

_TEST_ENV_DEFAULTS = {"DATA_S3_BUCKET": "test-bucket", "AWS_DEFAULT_REGION": "us-east-1"}


@contextmanager
def _lambda_test_env():
    """Set the handler's required env vars for the duration of the `with`
    block only, restoring whatever was there before (or removing the key
    entirely if it wasn't set) on exit -- so this module-scoped fixture
    doesn't leak DATA_S3_BUCKET/AWS_DEFAULT_REGION into the rest of the
    pytest session for tests that run after it in the same process."""
    originals = {k: os.environ.get(k) for k in _TEST_ENV_DEFAULTS}
    for k, v in _TEST_ENV_DEFAULTS.items():
        os.environ.setdefault(k, v)
    try:
        yield
    finally:
        for k, original in originals.items():
            if original is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = original


@pytest.fixture(scope="module")
def handler(tmp_path_factory):
    with _lambda_test_env():
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


# --- _lambda_test_env: regression for the DATA_S3_BUCKET/AWS_DEFAULT_REGION
# leak into the rest of the pytest session (M-6) --------------------------

def test_lambda_test_env_removes_vars_that_were_previously_unset():
    os.environ.pop("DATA_S3_BUCKET", None)
    os.environ.pop("AWS_DEFAULT_REGION", None)
    with _lambda_test_env():
        assert os.environ["DATA_S3_BUCKET"] == "test-bucket"
        assert os.environ["AWS_DEFAULT_REGION"] == "us-east-1"
    assert "DATA_S3_BUCKET" not in os.environ
    assert "AWS_DEFAULT_REGION" not in os.environ


def test_lambda_test_env_restores_vars_that_were_previously_set():
    os.environ["DATA_S3_BUCKET"] = "existing-bucket"
    os.environ["AWS_DEFAULT_REGION"] = "eu-west-1"
    try:
        with _lambda_test_env():
            # setdefault: an existing value is never overwritten.
            assert os.environ["DATA_S3_BUCKET"] == "existing-bucket"
            assert os.environ["AWS_DEFAULT_REGION"] == "eu-west-1"
        assert os.environ["DATA_S3_BUCKET"] == "existing-bucket"
        assert os.environ["AWS_DEFAULT_REGION"] == "eu-west-1"
    finally:
        os.environ.pop("DATA_S3_BUCKET", None)
        os.environ.pop("AWS_DEFAULT_REGION", None)
