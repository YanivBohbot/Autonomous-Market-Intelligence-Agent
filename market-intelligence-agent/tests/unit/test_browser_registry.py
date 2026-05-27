"""Verify the registry adds a 'browser' stdio entry pointing at our custom
server when BROWSER_BACKEND=agentcore, regardless of MCP_TRANSPORT."""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch


def _load_registry():
    """Load registry.py directly (bypassing app.agent.tools.__init__,
    which drags in langgraph/transformers and hits the Windows long-path bug)."""
    if "app.agent.tools.mcp_clients.registry" in sys.modules:
        return sys.modules["app.agent.tools.mcp_clients.registry"]
    base = Path(__file__).resolve().parents[2]  # market-intelligence-agent/
    spec = importlib.util.spec_from_file_location(
        "app.agent.tools.mcp_clients.registry",
        base / "app" / "agent" / "tools" / "mcp_clients" / "registry.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["app.agent.tools.mcp_clients.registry"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_browser_backend_agentcore_uses_custom_server(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKEND", "agentcore")
    monkeypatch.setenv("BROWSER_TOOL_ID", "arn:aws:bedrock-agentcore:us-east-1:1:browser/foo")
    monkeypatch.setenv("MCP_TRANSPORT", "gateway")
    monkeypatch.setenv("AGENTCORE_GATEWAY_URL", "https://example.com/mcp")

    # Force re-read of settings cache
    from app.core import config as cfg
    cfg.settings = cfg.Settings()

    # Reload registry so it picks up the fresh settings object
    sys.modules.pop("app.agent.tools.mcp_clients.registry", None)
    registry = _load_registry()
    # Also push fresh settings into the module's namespace
    registry.settings = cfg.settings

    with patch.object(registry, "_fetch_gateway_oauth_token", return_value=None):
        cfg_dict = registry._server_config()

    assert "browser" in cfg_dict
    browser = cfg_dict["browser"]
    assert browser["transport"] == "stdio"
    assert browser["command"] in {"python", "uv"}
    args = " ".join(browser["args"])
    assert "app.mcp.browser.server" in args
    assert browser["env"]["BROWSER_TOOL_ID"].startswith("arn:aws:bedrock-agentcore")


def test_browser_backend_local_uses_playwright_mcp(monkeypatch):
    monkeypatch.setenv("BROWSER_BACKEND", "local")
    monkeypatch.setenv("MCP_TRANSPORT", "stdio")

    from app.core import config as cfg
    cfg.settings = cfg.Settings()

    sys.modules.pop("app.agent.tools.mcp_clients.registry", None)
    registry = _load_registry()
    registry.settings = cfg.settings

    cfg_dict = registry._server_config()
    assert cfg_dict["browser"]["command"] == "npx"
    assert "@playwright/mcp@latest" in " ".join(cfg_dict["browser"]["args"])
