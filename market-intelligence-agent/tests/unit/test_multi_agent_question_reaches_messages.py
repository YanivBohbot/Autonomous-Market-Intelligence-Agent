"""Regression test for a live-QA-caught bug: finance_agent/portfolio_agent build
their LLM prompt from state["messages"], but nothing in the multi-agent
parent graph ever converted state["question"] into a HumanMessage the way
app.agent.graph.record_question does for the single-agent graph. Result:
specialists saw an empty message history and had no idea what was asked."""
from unittest.mock import patch
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent import finance_agent as finance_agent_mod
from app.agent.multi_agent.supervisor import RoutingDecision


def test_finance_specialist_sees_the_users_question_as_a_message():
    graph = build_multi_agent_app(InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    with patch.object(supervisor_mod, "_router") as router_mock, \
         patch.object(finance_agent_mod, "_llm_with_tools") as finance_llm_mock:
        router_mock.invoke.side_effect = [
            RoutingDecision(next="finance_agent", reasoning="stock question"),
            RoutingDecision(next="FINISH", reasoning="answered"),
        ]
        from langchain_core.messages import AIMessage
        finance_llm_mock.invoke.return_value = AIMessage(content="AAPL is at $200.")

        graph.invoke(
            {"question": "What's AAPL trading at?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0},
            config,
        )

        invoked_messages = finance_llm_mock.invoke.call_args[0][0]
        assert any(
            isinstance(m, HumanMessage) and "AAPL" in m.content
            for m in invoked_messages
        ), f"finance_agent never saw the user's question in its messages: {invoked_messages}"
