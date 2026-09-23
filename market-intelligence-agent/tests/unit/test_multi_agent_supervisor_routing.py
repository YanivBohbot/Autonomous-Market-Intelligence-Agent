from unittest.mock import patch
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import END

from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import supervisor_node, RoutingDecision, MAX_AGENT_HOPS


def _state(agent_hops=0, messages=None):
    return {"question": "q", "messages": messages or [], "documents": [], "next_agent": None, "agent_hops": agent_hops}


def test_finishes_deterministically_after_specialist_returns_a_plain_answer_without_calling_llm():
    """Regression: even with a strengthened prompt, live QA showed the LLM
    router unreliably re-routed to the same specialist to fetch the same
    answer again instead of picking FINISH — a non-determinism problem
    prompt wording alone couldn't fully fix. So this is now a deterministic
    code rule: once a specialist hands control back with a plain completed
    answer (no tool_calls), the turn is done — no further LLM call."""
    history = [HumanMessage(content="q"), AIMessage(content="the complete answer")]
    state = _state(agent_hops=1, messages=history)
    state["next_agent"] = "finance_agent"  # set by the specialist's own prior hop

    with patch.object(supervisor_mod, "_router") as mock:
        result = supervisor_node(state)

    mock.invoke.assert_not_called()
    assert result.goto == END
    assert result.update["next_agent"] is None


def test_still_asks_llm_on_the_very_first_hop():
    """next_agent is None before any specialist has run — must still route."""
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="stock question")
        result = supervisor_node(_state())

    mock.invoke.assert_called_once()
    assert result.goto == "finance_agent"


def test_router_is_not_given_a_duplicate_question_message():
    """Regression: supervisor used to re-inject a fresh HumanMessage("User's
    question: ...") on every hop, on top of the real conversation history
    (which already carries the question via record_question). Live QA showed
    this duplication made the router think the question was unanswered even
    after a specialist gave a correct, complete answer, causing it to loop to
    MAX_AGENT_HOPS instead of picking FINISH."""
    history = [HumanMessage(content="q"), AIMessage(content="the answer")]
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="FINISH", reasoning="answered")
        supervisor_node(_state(messages=history))

    invoked_messages = mock.invoke.call_args[0][0]
    assert invoked_messages == [SystemMessage(content=supervisor_mod.SUPERVISOR_ROUTING_PROMPT), *history]


def test_routes_to_finance_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="stock question")
        result = supervisor_node(_state())
    assert result.goto == "finance_agent"
    assert result.update["next_agent"] == "finance_agent"
    assert result.update["agent_hops"] == 1


def test_routes_to_crm_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="crm_agent", reasoning="customer question")
        result = supervisor_node(_state())
    assert result.goto == "crm_agent"


def test_routes_to_rag_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="rag_agent", reasoning="general question")
        result = supervisor_node(_state())
    assert result.goto == "rag_agent"


def test_routes_to_memory_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="memory_agent", reasoning="remember a fact")
        result = supervisor_node(_state())
    assert result.goto == "memory_agent"


def test_routes_to_filesystem_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="filesystem_agent", reasoning="file question")
        result = supervisor_node(_state())
    assert result.goto == "filesystem_agent"


def test_routes_to_browser_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="browser_agent", reasoning="check a website")
        result = supervisor_node(_state())
    assert result.goto == "browser_agent"


def test_routes_to_email_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="email_agent", reasoning="send an email")
        result = supervisor_node(_state())
    assert result.goto == "email_agent"


def test_finish_routes_to_end():
    history = [HumanMessage(content="q"), AIMessage(content="the answer")]
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="FINISH", reasoning="already answered")
        result = supervisor_node(_state(messages=history))
    assert result.goto == END
    assert result.update["next_agent"] is None


def test_finish_before_any_answer_falls_back_to_rag_agent():
    """Regression: live QA showed the router picking FINISH on the very first
    hop for multi-specialist questions ("Compare Amazon's 2024 net sales with
    Tesla's Q2 2026 revenue") — its own reasoning said "I need to route", yet
    it returned FINISH, ending the turn with no answer at all. FINISH is only
    valid once an AIMessage answers the latest HumanMessage; otherwise fall
    back to rag_agent, the general-purpose specialist."""
    history = [HumanMessage(content="Compare Amazon's 2024 net sales with Tesla's Q2 2026 revenue.")]
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="FINISH", reasoning="need to route")
        result = supervisor_node(_state(messages=history))
    assert result.goto == "rag_agent"
    assert result.update["next_agent"] == "rag_agent"
    assert result.update["agent_hops"] == 1


def test_finish_on_new_question_after_earlier_answer_falls_back_to_rag_agent():
    """Multi-turn thread: an AIMessage from a previous turn doesn't answer the
    new HumanMessage — only an AIMessage after the latest question counts."""
    history = [HumanMessage(content="q1"), AIMessage(content="a1"), HumanMessage(content="q2")]
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="FINISH", reasoning="answered")
        result = supervisor_node(_state(messages=history))
    assert result.goto == "rag_agent"


def test_hop_cap_short_circuits_without_calling_llm():
    with patch.object(supervisor_mod, "_router") as mock:
        result = supervisor_node(_state(agent_hops=MAX_AGENT_HOPS))
    assert result.goto == END
    mock.invoke.assert_not_called()
