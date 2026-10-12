"""Fake router_agent results for tests that patch supervisor_mod.router_agent."""
from app.agent.multi_agent.supervisor import RoutingDecision


def routed(next_agent: str, reasoning: str = "test") -> dict:
    return {"structured_response": RoutingDecision(next=next_agent, reasoning=reasoning), "messages": []}
