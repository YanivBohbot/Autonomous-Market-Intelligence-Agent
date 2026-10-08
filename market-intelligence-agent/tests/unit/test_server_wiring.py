import pytest
from fastapi import FastAPI

from app.api import server


@pytest.mark.anyio
async def test_lifespan_shares_one_multi_agent_graph_across_transports(monkeypatch):
    monkeypatch.setattr(server.settings, "CHECKPOINTER_BACKEND", "memory")
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", True)
    monkeypatch.setattr(server, "build_voice_agent_app", lambda checkpointer, store: object())
    test_app = FastAPI()

    async with server.lifespan(test_app):
        nodes = set(test_app.state.agent_app.get_graph().nodes)

        assert {
            "supervisor",
            "rag_agent",
            "finance_agent",
            "portfolio_agent",
            "browser_agent",
            "memory_agent",
            "filesystem_agent",
            "email_agent",
        } <= nodes
        assert test_app.state.market_desk_agent.graph is test_app.state.agent_app
