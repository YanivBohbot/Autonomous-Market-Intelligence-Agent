"""Old tool results are cleared from what the MODEL sees, never from the
checkpointed conversation -- Market Desk renders its cards from that state."""
from unittest.mock import patch

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import ContextEditingMiddleware
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.messages.utils import count_tokens_approximately

from app.agent import middleware as mw
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel

BIG = "x" * 4000  # ~1000 tokens per tool result


def _turn(n: int, tool_name: str = "client_portfolio") -> list:
    call = {"id": f"c{n}", "name": tool_name, "args": {"client_name": f"Client {n}"}}
    return [
        HumanMessage(f"question {n}"),
        AIMessage(content="", tool_calls=[call]),
        ToolMessage(content=f"RESULT{n} {BIG}", tool_call_id=f"c{n}", name=tool_name),
        AIMessage(content=f"answer {n}"),
    ]


def _history(turns: int) -> list:
    messages = []
    for n in range(1, turns + 1):
        messages += _turn(n)
    return messages


def _tool_contents(messages) -> list[str]:
    return [m.content[:7] for m in messages if isinstance(m, ToolMessage)]


def test_clears_tool_results_older_than_the_two_previous_turns():
    messages = _history(5) + [HumanMessage("question 6")]
    mw.ClearOldTurnToolResults().apply(messages, count_tokens=count_tokens_approximately)
    # Turns 1-3 cleared; turns 4-5 (the two previous turns) kept verbatim.
    assert _tool_contents(messages) == ["[cleare", "[cleare", "[cleare", "RESULT4", "RESULT5"]


def test_never_clears_the_current_turn_even_with_many_tool_calls():
    messages = _history(4)
    current = [HumanMessage("compare three docs")]
    for i in range(4):
        call = {"id": f"s{i}", "name": "search_knowledge_base", "args": {"query": f"q{i}"}}
        current += [AIMessage(content="", tool_calls=[call]),
                    ToolMessage(content=f"CURRENT{i} {BIG}", tool_call_id=f"s{i}", name="search_knowledge_base")]
    messages += current
    mw.ClearOldTurnToolResults().apply(messages, count_tokens=count_tokens_approximately)
    assert [c for c in _tool_contents(messages) if c.startswith("CURRENT")] == ["CURRENT"] * 4


def test_keeps_tool_call_arguments_so_follow_ups_still_know_the_ticker():
    messages = _history(5) + [HumanMessage("and its 3-month history?")]
    mw.ClearOldTurnToolResults().apply(messages, count_tokens=count_tokens_approximately)
    assert messages[1].tool_calls[0]["args"] == {"client_name": "Client 1"}


def test_does_nothing_below_the_token_trigger():
    messages = _history(5) + [HumanMessage("q")]
    mw.ClearOldTurnToolResults(trigger=10**9).apply(messages, count_tokens=count_tokens_approximately)
    assert "[cleare" not in _tool_contents(messages)


def test_base_middleware_includes_context_editing():
    assert any(isinstance(m, ContextEditingMiddleware) for m in mw.base_middleware([]))


@pytest.mark.anyio
async def test_model_sees_cleared_results_but_the_stored_conversation_keeps_them():
    model = FakeToolModel([AIMessage(content="done")])
    agent = create_agent(model=model, tools=[], system_prompt="X", middleware=[mw.context_editing()])
    history = _history(5) + [HumanMessage("question 6")]
    result = await agent.ainvoke({"messages": history})
    seen_tools = [m for m in model.seen[0] if isinstance(m, ToolMessage)]
    assert seen_tools[0].content == "[cleared]"
    stored_tools = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert stored_tools[0].content.startswith("RESULT1")


def test_supervisor_router_gets_old_tool_results_cleared_and_state_is_untouched():
    history = _history(5) + [HumanMessage("question 6")]
    state = {"messages": history, "next_agent": None, "agent_hops": 0}
    with patch.object(supervisor_mod, "_router") as router:
        router.invoke.return_value = RoutingDecision(next="rag_agent", reasoning="r")
        supervisor_mod.supervisor_node(state)
    sent = router.invoke.call_args.args[0]
    assert _tool_contents(sent)[:3] == ["[cleare"] * 3
    assert _tool_contents(history)[0] == "RESULT1"
