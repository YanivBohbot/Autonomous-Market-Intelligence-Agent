"""End-to-end with every LLM mocked: supervisor routes to a create_agent
specialist, the specialist answers, the static edge brings control back to
the supervisor, which finishes deterministically."""
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app
from app.agent.multi_agent import finance_agent as finance_agent_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel


def test_supervisor_routes_to_finance_then_finishes():
    fake = FakeToolModel([AIMessage(content="AAPL is trading at $200.")])
    with patch.object(finance_agent_mod, "specialist_model", return_value=fake), \
         patch.object(supervisor_mod, "_router") as router_mock:
        router_mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="stock question")
        graph = build_multi_agent_app(InMemorySaver())
        result = graph.invoke(
            {"question": "AAPL price?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0},
            {"configurable": {"thread_id": "t1"}},
        )

    assert result["messages"][-1].content == "AAPL is trading at $200."
    # Deterministic finish: no second routing call after the specialist answered.
    assert router_mock.invoke.call_count == 1
