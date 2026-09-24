"""Regression: specialists read state["messages"]; record_question must turn
state["question"] into a HumanMessage they actually receive."""
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app
from app.agent.multi_agent import finance_agent as finance_agent_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel


def test_finance_specialist_sees_the_users_question_as_a_message():
    fake = FakeToolModel([AIMessage(content="AAPL is at $200.")])
    with patch.object(finance_agent_mod, "specialist_model", return_value=fake), \
         patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="stock question")
        graph = build_multi_agent_app(InMemorySaver())
        graph.invoke(
            {"question": "What's AAPL trading at?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0},
            {"configurable": {"thread_id": "t1"}},
        )

    invoked = fake.seen[0]
    assert any(isinstance(m, HumanMessage) and "AAPL" in m.content for m in invoked), invoked
