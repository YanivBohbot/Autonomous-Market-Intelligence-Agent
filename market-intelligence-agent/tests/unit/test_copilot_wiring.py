"""COPILOT_ENABLED gates Market Desk: off by default (404), and when on the
lifespan attaches the agent to app.state."""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from app.api import server
from app.api.routers.copilot import MARKET_DESK_AGENT_NAME
from app.core.config import Settings


def test_disabled_by_default():
    # Default of the field itself: the local .env may turn it on.
    assert Settings.model_fields["COPILOT_ENABLED"].default is False


def test_routes_absent_when_disabled_return_404(monkeypatch):
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", False)
    app = FastAPI()
    server.include_market_desk_routes(app)
    assert TestClient(app).post("/copilot/market-desk", json={}).status_code == 404


def test_routes_present_when_enabled(monkeypatch):
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", True)
    app = FastAPI()
    server.include_market_desk_routes(app)
    # Route exists; no agent attached yet, so it answers 503 (not 404).
    body = {"threadId": "t", "runId": "r", "messages": []}
    assert TestClient(app).post("/copilot/market-desk", json=body).status_code == 503


def test_setup_market_desk_attaches_agent_when_enabled(monkeypatch):
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", True)
    app = FastAPI()
    server.setup_market_desk(app, InMemorySaver(), None)
    assert app.state.market_desk_agent.name == MARKET_DESK_AGENT_NAME


def test_setup_market_desk_is_a_no_op_when_disabled(monkeypatch):
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", False)
    app = FastAPI()
    server.setup_market_desk(app, InMemorySaver(), None)
    assert not hasattr(app.state, "market_desk_agent")


def test_server_imports_without_ag_ui_installed():
    # The AgentCore image installs requirements.agentcore.txt, which has no
    # ag-ui packages (Market Desk is local-only): server.py must still import.
    import os
    import subprocess
    import sys

    code = (
        "import sys\n"
        "for m in ('ag_ui', 'ag_ui.core', 'ag_ui.core.types', 'ag_ui.encoder', 'ag_ui_langgraph'):\n"
        "    sys.modules[m] = None\n"
        "import app.api.server\n"
        "print('ok')\n"
    )
    env = {**os.environ, "COPILOT_ENABLED": "false"}
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert proc.stdout.strip().endswith("ok")
