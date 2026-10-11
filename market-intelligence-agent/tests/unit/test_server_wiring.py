import pytest
from fastapi import FastAPI

from app.api import server
from app.agent.turn_coordinator import ThreadTurnCoordinator
from app.voice.activity_store import VoiceActivityStore
from app.voice.research_runtime import ResearchVoiceRuntime


@pytest.mark.anyio
async def test_lifespan_shares_one_multi_agent_graph_across_transports(monkeypatch):
    monkeypatch.setattr(server.settings, "CHECKPOINTER_BACKEND", "memory")
    monkeypatch.setattr(server.settings, "COPILOT_ENABLED", True)
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
        assert isinstance(test_app.state.turn_coordinator, ThreadTurnCoordinator)
        assert isinstance(test_app.state.voice_activity_store, VoiceActivityStore)
        assert isinstance(test_app.state.research_voice_runtime, ResearchVoiceRuntime)
        assert test_app.state.research_voice_runtime.graph is test_app.state.agent_app
