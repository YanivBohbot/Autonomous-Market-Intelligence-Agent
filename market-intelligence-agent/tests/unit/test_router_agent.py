"""The supervisor's router agent: create_agent + response_format + official
middleware. Fake model only: without native structured output support,
create_agent falls back to ToolStrategy, so the fake answers with a tool
call named after the schema (RoutingDecision)."""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision, build_router_agent
from tests.unit.fake_chat import FakeToolModel

BIG = "x" * 4000


def _decides(next_agent: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{
        "id": "rd1", "name": "RoutingDecision", "args": {"next": next_agent, "reasoning": "r"}}])


def test_returns_the_structured_decision():
    model = FakeToolModel([_decides("finance_agent")])
    result = build_router_agent(model).invoke({"messages": [HumanMessage("NVDA price?")]})
    assert result["structured_response"] == RoutingDecision(next="finance_agent", reasoning="r")


def test_prompt_lists_the_ingested_documents_live(tmp_path, monkeypatch):
    """A PDF uploaded through /data/import/pdf while the server runs must be
    visible to the router on the next call, not only after a restart."""
    manifest = tmp_path / "kb_documents.json"
    manifest.write_text('["brand-new-upload.pdf"]', encoding="utf-8")
    monkeypatch.setattr(
        "app.agent.prompts.specialist_agent_prompts._KB_MANIFEST_PATH", manifest
    )
    model = FakeToolModel([_decides("rag_agent")])
    build_router_agent(model).invoke({"messages": [HumanMessage("what's in the new upload?")]})
    assert "brand-new-upload.pdf" in model.seen[0][0].content


def test_prompt_mentions_the_active_client_only_when_set():
    model = FakeToolModel([_decides("portfolio_agent"), _decides("rag_agent")])
    agent = build_router_agent(model)
    agent.invoke({"messages": [HumanMessage("who is the client?")],
                  "client_context": "Active client: Jane Doe, segment VIP, risk balanced, advisor Sam."})
    agent.invoke({"messages": [HumanMessage("who is the client?")]})
    assert "Active client: Jane Doe" in model.seen[0][0].content
    assert "prefer portfolio_agent" in model.seen[0][0].content
    assert "Active client" not in model.seen[1][0].content


def test_old_turn_tool_results_reach_the_model_cleared():
    history = []
    for n in range(1, 6):
        call = {"id": f"c{n}", "name": "client_portfolio", "args": {}}
        history += [HumanMessage(f"q{n}"), AIMessage(content="", tool_calls=[call]),
                    ToolMessage(content=f"RESULT{n} {BIG}", tool_call_id=f"c{n}", name="client_portfolio"),
                    AIMessage(content=f"a{n}")]
    model = FakeToolModel([_decides("rag_agent")])
    build_router_agent(model).invoke({"messages": [*history, HumanMessage("q6")]})
    tool_contents = [m.content[:7] for m in model.seen[0] if isinstance(m, ToolMessage)]
    assert tool_contents[:3] == ["[cleare"] * 3


def test_a_card_blocks_the_router_with_no_structured_response():
    model = FakeToolModel([_decides("rag_agent")])
    result = build_router_agent(model).invoke({"messages": [HumanMessage("card 4111 1111 1111 1111", id="h1")]})
    assert model.seen == []
    assert "structured_response" not in result


def test_module_router_agent_is_built():
    assert hasattr(supervisor_mod.router_agent, "invoke")
