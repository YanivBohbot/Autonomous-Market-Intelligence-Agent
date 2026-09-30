from unittest.mock import patch
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langgraph.graph import END

from app.agent.multi_agent import supervisor as supervisor_mod
from app.agent.multi_agent.supervisor import supervisor_node, RoutingDecision, MAX_AGENT_HOPS


def _state(agent_hops=0, messages=None, last_agent=None):
    return {
        "question": "q",
        "messages": messages or [],
        "documents": [],
        "next_agent": None,
        "agent_hops": agent_hops,
        "last_agent": last_agent,
    }


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


def test_routes_to_portfolio_agent():
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="portfolio_agent", reasoning="client portfolio question")
        result = supervisor_node(_state())
    assert result.goto == "portfolio_agent"
    assert result.update["last_agent"] == "portfolio_agent"


def test_sticky_routes_back_to_portfolio_agent_without_calling_llm_when_human_confirms_saving():
    """Regression: two rounds of prose/worked-example prompt fixes both failed
    live re-testing -- "Yes, save it as a downloadable report" (a follow-up to
    portfolio_agent's own offer) still got routed to filesystem_agent by the
    LLM router, producing a hand-typed .txt with no chart. Prompt wording
    alone isn't reliable here, so this is now a deterministic code rule, the
    same class of fix as the existing FINISH-after-plain-answer rule: a fresh
    human turn that mentions save/export/download, right after portfolio_agent
    itself last answered, stays with portfolio_agent -- no LLM call."""
    history = [
        HumanMessage(content="Generate a portfolio report for Margaret Collins"),
        AIMessage(content="I've generated the portfolio report. Let me know if you'd like to save or export it."),
        HumanMessage(content="Yes, save it as a downloadable report"),
    ]
    state = _state(messages=history, last_agent="portfolio_agent")

    with patch.object(supervisor_mod, "_router") as mock:
        result = supervisor_node(state)

    mock.invoke.assert_not_called()
    assert result.goto == "portfolio_agent"
    assert result.update["next_agent"] == "portfolio_agent"
    assert result.update["last_agent"] == "portfolio_agent"
    assert result.update["agent_hops"] == 1


def test_sticky_rule_does_not_fire_when_the_prior_answer_never_mentioned_a_report():
    """Regression (final review): the sticky rule fired for ANY save/export/
    download follow-up after ANY portfolio_agent turn, not just a follow-up
    to a report offer. "What's Margaret's portfolio worth?" -> "Save that my
    investment horizon is 10 years" (a memory_agent request) would have stuck
    to portfolio_agent, which has no save_memory tool -- the fact never gets
    saved. Requiring the prior AIMessage to mention report/brief scopes the
    rule to the actual bug it was written to fix."""
    history = [
        HumanMessage(content="What's Margaret's portfolio worth?"),
        AIMessage(content="Margaret's portfolio is worth $156,078."),
        HumanMessage(content="Save that my investment horizon is 10 years"),
    ]
    state = _state(messages=history, last_agent="portfolio_agent")

    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="memory_agent", reasoning="remember a fact")
        result = supervisor_node(state)

    mock.invoke.assert_called_once()
    assert result.goto == "memory_agent"


def test_sticky_rule_does_not_fire_when_last_agent_was_not_portfolio_agent():
    history = [
        HumanMessage(content="What files are in the workspace?"),
        AIMessage(content="You have notes.txt and report.html."),
        HumanMessage(content="Yes, save it as a downloadable report"),
    ]
    state = _state(messages=history, last_agent="filesystem_agent")

    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="filesystem_agent", reasoning="file question")
        result = supervisor_node(state)

    mock.invoke.assert_called_once()
    assert result.goto == "filesystem_agent"


def test_sticky_rule_check_survives_list_typed_message_content():
    """Defensive: AG-UI can in principle deliver HumanMessage.content as a
    list of content blocks (multimodal), not a plain str. A naive regex
    .search(last.content) would raise TypeError and crash the whole graph
    run over a routing heuristic. The text must be extracted the same way
    display._content_text already does for ToolMessage content, so the rule
    still works correctly instead of just not-crashing."""
    history = [
        HumanMessage(content="Generate a portfolio report for Margaret Collins"),
        AIMessage(content="I've generated the portfolio report. Let me know if you'd like to save or export it."),
        HumanMessage(content=[{"type": "text", "text": "Yes, save it as a downloadable report"}]),
    ]
    state = _state(messages=history, last_agent="portfolio_agent")

    with patch.object(supervisor_mod, "_router") as mock:
        result = supervisor_node(state)  # must not raise

    mock.invoke.assert_not_called()
    assert result.goto == "portfolio_agent"


def test_sticky_rule_does_not_fire_when_the_new_message_has_no_save_language():
    """A genuinely new question right after portfolio_agent answered must
    still go through the router, not stick to portfolio_agent by default."""
    history = [
        HumanMessage(content="Generate a portfolio report for Margaret Collins"),
        AIMessage(content="I've generated the portfolio report. Let me know if you'd like to save or export it."),
        HumanMessage(content="What's Tesla's stock price?"),
    ]
    state = _state(messages=history, last_agent="portfolio_agent")

    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="stock price question")
        result = supervisor_node(state)

    mock.invoke.assert_called_once()
    assert result.goto == "finance_agent"


def test_routing_prompt_describes_portfolio_agent_not_crm_agent():
    assert "portfolio_agent" in supervisor_mod.SUPERVISOR_ROUTING_PROMPT
    assert "crm_agent" not in supervisor_mod.SUPERVISOR_ROUTING_PROMPT


def test_routing_prompt_lists_ingested_documents_so_rag_isnt_skipped_for_them():
    """Regression: with no document names in the prompt, the router had no
    way to recognize "Tesla's Q2 2026 update" as an ingested PDF rather than
    a request to check a live website, so it sent Tesla questions to
    browser_agent instead of rag_agent — live QA reproduced this, and it
    only worked once the user explicitly said "internal documents"."""
    assert "Tesla-TSLA-Q2-2026-Update.pdf" in supervisor_mod.SUPERVISOR_ROUTING_PROMPT
    assert "Amazon-2024-Annual-Report.pdf" in supervisor_mod.SUPERVISOR_ROUTING_PROMPT


def test_routing_prompt_keeps_saving_a_portfolio_report_with_portfolio_agent():
    """Regression: live QA showed "Yes, save it as a downloadable report"
    (a follow-up to a portfolio_agent answer) get routed to filesystem_agent
    instead -- both bullets said "save" without distinguishing a portfolio
    report (portfolio_agent now owns write_file too) from a generic
    workspace file. filesystem_agent then wrote a hand-typed .txt summary
    with no chart, completely bypassing generate_portfolio_report."""
    prompt = supervisor_mod.SUPERVISOR_ROUTING_PROMPT
    portfolio_bullet = prompt.split("- portfolio_agent")[1].split("\n-")[0]
    filesystem_bullet = prompt.split("- filesystem_agent")[1].split("\n-")[0]
    assert "report" in portfolio_bullet.lower()
    assert "portfolio" in filesystem_bullet.lower()


def test_routing_prompt_has_a_worked_example_for_saving_a_portfolio_report():
    """Regression: the prose disambiguation alone (added above) did not
    change the LLM's actual routing decision in live re-testing -- it still
    sent "Yes, save it as a downloadable report" to filesystem_agent. A
    concrete worked example is what fixed the analogous RAG/Tesla misroute
    earlier this session; apply the same fix here."""
    prompt = supervisor_mod.SUPERVISOR_ROUTING_PROMPT
    assert "save it as a downloadable report" in prompt.lower()
    # The example must appear after the portfolio_agent's own answer, in the
    # same worked-example block style as the existing FINISH example.
    example_section = prompt.rsplit("Example:", 1)[1]
    assert "portfolio_agent" in example_section
    assert "filesystem_agent" in example_section


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


def test_a_new_turns_human_message_resets_hops_left_over_from_earlier_turns():
    """Regression: agent_hops was never reset between turns, so it accumulated
    across the WHOLE conversation instead of per turn. After ~4 hops total —
    often just 2-3 user turns — the hop cap above silently short-circuited to
    FINISH with no LLM call and no answer, for every later turn: live QA (and
    this session's own manual testing) hit exactly this, "the agent doesn't
    respond anymore" after a handful of questions, no error anywhere. A fresh
    HumanMessage means record_question just ran for a NEW question, so hops
    left over from a previous turn must not count against this one."""
    history = [HumanMessage(content="q1"), AIMessage(content="a1"), HumanMessage(content="q2")]
    with patch.object(supervisor_mod, "_router") as mock:
        mock.invoke.return_value = RoutingDecision(next="finance_agent", reasoning="new question")
        result = supervisor_node(_state(agent_hops=MAX_AGENT_HOPS, messages=history))

    mock.invoke.assert_called_once()
    assert result.goto == "finance_agent"
    assert result.update["agent_hops"] == 1


def test_hops_still_cap_mid_turn_even_right_after_a_human_message_was_seen_earlier():
    """The reset only applies when the human message is the LAST message
    (a turn just started); hops accumulated within the CURRENT turn (after
    that human message, via one or more specialist hops) must still cap."""
    history = [HumanMessage(content="q"), AIMessage(content="", tool_calls=[])]
    with patch.object(supervisor_mod, "_router") as mock:
        result = supervisor_node(_state(agent_hops=MAX_AGENT_HOPS, messages=history))
    assert result.goto == END
    mock.invoke.assert_not_called()


def test_router_output_is_hidden_from_ag_ui_streams():
    # ag-ui-langgraph streams via astream_events and drops LLM chunks whose run
    # metadata says emit-messages/emit-tool-calls False. The routing JSON
    # ({"next": ...}) must never show up as chat text in Market Desk.
    metadata = supervisor_mod._router.config["metadata"]
    assert metadata["emit-messages"] is False
    assert metadata["emit-tool-calls"] is False
