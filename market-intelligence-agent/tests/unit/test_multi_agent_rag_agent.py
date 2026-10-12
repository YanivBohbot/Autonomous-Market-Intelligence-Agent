from unittest.mock import patch

from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.agents_specialist import rag_agent as mod
from app.agent.middleware import RedactEmailsForModel, base_middleware, client_context_prompt, fresh_documents_prompt
from app.agent.display import market_desk_display
from app.agent.orchestration.state import ClientContextState


def _kwargs():
    with patch.object(mod, "create_agent") as ca:
        mod.build_rag_agent()
    return ca.call_args.kwargs


def test_tools():
    assert {t.name for t in mod._TOOLS} == {"search_knowledge_base", "web_search"}


def test_create_agent_call():
    kw = _kwargs()
    from app.agent.prompts.specialist_agent_prompts import RAG_SYSTEM_PROMPT
    assert kw["system_prompt"] == RAG_SYSTEM_PROMPT
    assert kw["tools"] == mod._TOOLS
    assert kw["name"] == "rag_agent"
    assert kw["state_schema"] is ClientContextState
    mw = kw["middleware"]
    base = base_middleware(mod._TOOLS)
    assert [type(m) for m in mw[:len(base)]] == [type(m) for m in base]
    # Queries go to third parties (Tavily / Yahoo): emails are redacted first.
    assert isinstance(mw[len(base)], RedactEmailsForModel)
    # Substitutes the live manifest into RAG_SYSTEM_PROMPT's placeholder at
    # call time -- a PDF uploaded while the server is running must be
    # visible immediately, not only after a restart.
    # Caps Tavily calls per run (ToolCallLimitMiddleware).
    assert (mw[len(base) + 1].tool_name, mw[len(base) + 1].run_limit) == ("web_search", 3)
    assert mw[len(base) + 2] is fresh_documents_prompt
    assert mw[len(base) + 3] is client_context_prompt
    assert mw[len(base) + 4] is market_desk_display
    assert len(mw) == len(base) + 5
    assert not any(isinstance(m, HumanInTheLoopMiddleware) for m in kw["middleware"])


def test_builds_a_real_agent():
    assert "model" in mod.build_rag_agent().get_graph().nodes
