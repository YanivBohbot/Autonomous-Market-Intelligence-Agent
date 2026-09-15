"""End-to-end smoke test with every LLM call mocked: verifies the
Command(graph=Command.PARENT) handoff from a specialist subgraph back to the
parent's "supervisor" node actually works at runtime (not just that each
piece compiles in isolation) — the compiled graph's own mermaid drawing
shows specialists statically pointing at __end__ (a visualization artifact
of stripping the Literal[...] return-type annotation to dodge the
compile-time validation bug, see finance_agent.py), so this test exists to
prove the dynamic parent handoff still functions despite that."""
from unittest.mock import patch
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent import finance_agent as finance_agent_mod
from app.agent.multi_agent.supervisor import RoutingDecision


def test_supervisor_routes_to_finance_then_finishes():
    graph = build_multi_agent_app(InMemorySaver())
    config = {"configurable": {"thread_id": "t1"}}

    final_answer = AIMessage(content="AAPL is trading at $200.")

    with patch.object(supervisor_mod, "_router") as router_mock, \
         patch.object(finance_agent_mod, "_llm_with_tools") as finance_llm_mock:
        router_mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="stock question")
        finance_llm_mock.invoke.return_value = final_answer

        result = graph.invoke(
            {"question": "AAPL price?", "messages": [], "documents": [], "next_agent": None, "agent_hops": 0},
            config,
        )

    assert result["messages"][-1].content == "AAPL is trading at $200."
    # Only one LLM router call: the deterministic finish rule in
    # supervisor_node recognizes finance_agent's completed answer (no
    # tool_calls) and ends the turn without a second routing call.
    assert router_mock.invoke.call_count == 1
