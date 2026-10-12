"""The supervisor's router agent: create_agent + response_format + official
middleware. Fake model only: without native structured output support,
create_agent falls back to ToolStrategy, so the fake answers with a tool
call named after the schema (RoutingDecision)."""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.orchestration import supervisor as supervisor_mod
from app.agent.orchestration.supervisor import RoutingDecision, build_router_agent
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


# --- Final-review fix pass (2026-10-12) -------------------------------------

def test_router_uses_tool_strategy_with_one_decision_per_call():
    """Live bug (LangSmith trace 01a13021): with ProviderStrategy create_agent
    always sends `tools: []`, and gpt-4o-mini then emitted TWO routing JSON
    objects (3/3 vs 0/3 without the empty list) -> parse error -> retries.
    ToolStrategy + parallel_tool_calls=False allows exactly one decision."""
    built = {}

    def fake_chat_openai(**kwargs):
        built.update(kwargs)
        return FakeToolModel([])

    from unittest.mock import patch
    with patch.object(supervisor_mod, "ChatOpenAI", fake_chat_openai):
        supervisor_mod.build_router_agent()
    assert built["model_kwargs"] == {"parallel_tool_calls": False}
    from langchain.agents.structured_output import ToolStrategy
    assert isinstance(supervisor_mod._ROUTER_RESPONSE_FORMAT, ToolStrategy)


class _RaisingModel(FakeToolModel):
    def _generate(self, messages, *args, **kwargs):
        self.seen.append(list(messages))
        raise RuntimeError("provider down")


def test_a_failing_router_model_raises_instead_of_looping():
    """Reviewer Critical 1: ModelRetryMiddleware(on_failure="continue") turned
    an outage into an AIMessage without structured_response, and create_agent
    sent it back to the model up to 9,999 times. It must raise, fast."""
    import pytest
    model = _RaisingModel([])
    with pytest.raises(Exception):
        build_router_agent(model).invoke({"messages": [HumanMessage("NVDA?")]})
    assert len(model.seen) <= 9  # bounded: retries x call cap, never thousands


def test_a_router_that_never_produces_a_decision_raises():
    """Two parallel decisions (or none) every time must hit the call cap and
    raise, not loop."""
    import pytest
    two = AIMessage(content="", tool_calls=[
        {"id": "a", "name": "RoutingDecision", "args": {"next": "portfolio_agent", "reasoning": "r"}},
        {"id": "b", "name": "RoutingDecision", "args": {"next": "email_agent", "reasoning": "r"}}])
    model = FakeToolModel([two] * 20)
    with pytest.raises(Exception):
        build_router_agent(model).invoke({"messages": [HumanMessage("email her")]})
    assert len(model.seen) <= 9


def test_router_is_not_named_so_ag_ui_does_not_see_a_subagent():
    """Reviewer Important 1: name= sets lc_agent_name, and ag-ui-langgraph
    then emits SUBAGENT_STARTED/STEP events for the router in Market Desk."""
    agent = build_router_agent(FakeToolModel([]))
    assert "lc_agent_name" not in ((agent.config or {}).get("metadata") or {})


def test_router_runs_do_not_write_checkpoints():
    """Reviewer Important 2: the nested router inherited the graph's
    checkpointer and wrote a full conversation copy per call."""
    from unittest.mock import patch
    from langgraph.checkpoint.memory import InMemorySaver
    from app.agent.orchestration.graph import build_multi_agent_app
    from app.agent.agents_specialist import rag_agent as rag_mod

    saver = InMemorySaver()
    with patch.object(supervisor_mod, "router_agent", build_router_agent(FakeToolModel([_decides("rag_agent")]))), \
         patch.object(rag_mod, "specialist_model", return_value=FakeToolModel([AIMessage(content="ok")])):
        build_multi_agent_app(saver).invoke({"question": "what's new?"}, {"configurable": {"thread_id": "ck"}})
    namespaces = {c.config["configurable"].get("checkpoint_ns", "") for c in saver.list({"configurable": {"thread_id": "ck"}})}
    assert not any(ns.startswith("supervisor:") for ns in namespaces)
