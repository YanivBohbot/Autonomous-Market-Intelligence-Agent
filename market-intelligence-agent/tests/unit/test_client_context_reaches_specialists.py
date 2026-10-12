"""client_context, set by load_client_context from the thread id, must
actually reach the specialist that answers -- the easy mistake is wiring
the parent graph's state field and forgetting the specialist's own
state_schema, which silently makes request.state.get("client_context")
always None inside the specialist (see Review Focus in the plan)."""
import sqlite3
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver

from app.agent.multi_agent import build_multi_agent_app
import app.agent.multi_agent.graph as graph_module
from app.agent.multi_agent import portfolio_agent as portfolio_agent_mod
from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import RoutingDecision
from tests.unit.fake_chat import FakeToolModel
from tests.unit.router_fakes import routed


def test_portfolio_agent_sees_the_active_client_in_its_system_prompt(tmp_path, monkeypatch):
    db_path = tmp_path / "customers.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE clients (
            client_id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE,
            segment TEXT NOT NULL, risk_profile TEXT NOT NULL, advisor TEXT NOT NULL,
            city TEXT NOT NULL, joined_on DATE NOT NULL
        );
        CREATE TABLE companies (ticker TEXT PRIMARY KEY, name TEXT NOT NULL, sector TEXT NOT NULL);
        CREATE TABLE holdings (
            client_id INTEGER NOT NULL, ticker TEXT NOT NULL, shares REAL NOT NULL, avg_cost REAL NOT NULL
        );
    """)
    # Deliberately not "Margaret Collins" -- that name is a worked example
    # baked into PORTFOLIO_SYSTEM_PROMPT's static text, which made an
    # earlier version of this test pass for the wrong reason (the name
    # was already in the prompt, regardless of whether client_context
    # wiring worked at all). A name absent from every static prompt is
    # the only way this assertion actually proves the wiring.
    conn.execute(
        "INSERT INTO clients VALUES (1, 'Priya Desai', 'pd@x.com', 'VIP', 'conservative', 'Sam', 'Paris', '2024-01-01')"
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(graph_module, "DB_PATH", str(db_path))

    fake = FakeToolModel([AIMessage(content="Your portfolio is worth $100.")])
    with patch.object(portfolio_agent_mod, "specialist_model", return_value=fake), \
         patch.object(supervisor_mod, "router_agent") as router_mock:
        router_mock.invoke.return_value = routed("portfolio_agent", "portfolio question")
        graph = build_multi_agent_app(InMemorySaver())
        graph.invoke(
            {"question": "What's my portfolio worth?", "messages": [], "documents": [],
             "next_agent": None, "agent_hops": 0},
            {"configurable": {"thread_id": "clients_1"}},
        )

    system_text = fake.seen[0][0].content
    assert "Priya Desai" in system_text
