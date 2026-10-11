import re
from typing import Literal, cast

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.types import Command

from app.core.config import settings
from app.agent.multi_agent.state import SupervisorState
from app.agent.prompts.specialist_agent_prompts import (
    INGESTED_DOCUMENTS_PLACEHOLDER,
    SUPERVISOR_ROUTING_PROMPT,
    ingested_documents_list,
)


SpecialistName = Literal[
    "rag_agent",
    "finance_agent",
    "portfolio_agent",
    "memory_agent",
    "filesystem_agent",
    "browser_agent",
    "email_agent",
]
# Where the supervisor can send control: a specialist or the finalizer.
Route = Literal[SpecialistName, "finalize_turn"]


def _finish() -> Command[Route]:
    return Command(goto="finalize_turn", update={"next_agent": None})


class RoutingDecision(BaseModel):
    next: SpecialistName | Literal["FINISH"] = Field(
        description="Which specialist should act next, or FINISH if the "
        "conversation already has a complete answer to the user's question."
    )
    reasoning: str = Field(description="One sentence: why this specialist (or FINISH).")


# Deliberately not the official `langgraph-supervisor` package (handoff
# tools the LLM calls, routed via Command(goto=..., graph=Command.PARENT)):
# that pattern gives the LLM the routing decision as a tool call, with no
# plain-Python hook before it takes effect. The sticky-rule override below
# (a deterministic route that skips the LLM entirely for one specific
# follow-up) needs exactly that hook, so this supervisor stays a plain node
# that calls `with_structured_output` itself and returns `Command` directly.
_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
# The routing decision is internal: Market Desk (ag-ui-langgraph, which streams
# via astream_events) must not render its JSON as chat text. The decision stays
# visible through state.next_agent and STEP_STARTED events.
_router = _llm.with_structured_output(RoutingDecision).with_config(
    metadata={"emit-messages": False, "emit-tool-calls": False}
)

MAX_AGENT_HOPS = 4

# Matches app/voice/hitl.py's precedent of a lightweight keyword classifier
# for a resume/continuation decision, rather than another LLM call.
_SAVE_LANGUAGE_RE = re.compile(r"\b(save|export|download)\b", re.IGNORECASE)
# The sticky rule below must also confirm the PRIOR turn was actually about a
# report -- otherwise "save"/"export"/"download" alone is ambiguous with a
# memory_agent or finance_agent request that happens to follow a portfolio
# question (see test_sticky_rule_does_not_fire_when_the_prior_answer_never_mentioned_a_report).
_REPORT_LANGUAGE_RE = re.compile(r"\b(report|brief)\b", re.IGNORECASE)


_EMAIL_REQUEST_RE = re.compile(r"\b(e-?mail|send)\b", re.IGNORECASE)


def _latest_human_text(messages: list) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            return _message_text(m)
    return ""


def _message_text(message) -> str:
    """Same shape as display._content_text: message.content is normally a
    plain str, but AG-UI/MCP content can in principle be a list of blocks
    ([{"type": "text", "text": ...}, ...]). A regex against the raw content
    would crash the whole graph run on a routing heuristic if it ever isn't
    a string."""
    content = getattr(message, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content or "")


def supervisor_node(state: SupervisorState) -> Command[Route]:
    # agent_hops is a per-turn recursion guard. record_question appends the
    # new HumanMessage before this node runs, so a fresh HumanMessage as the
    # last message means a new turn just started: any hops left over from a
    # previous turn no longer apply. Without this reset, hops accumulated
    # across the WHOLE conversation instead of per turn, and after ~4 hops
    # total (often just 2-3 user turns) the supervisor would silently
    # short-circuit to FINISH below with no LLM call and no answer, for
    # every subsequent turn of the conversation.
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    hops = 0 if isinstance(last, HumanMessage) else state.get("agent_hops", 0)
    if hops >= MAX_AGENT_HOPS:
        return _finish()

    # Deterministic finish: once a specialist hands control back with a
    # plain completed answer (no further tool_calls), the turn is done.
    # Live QA showed the LLM router unreliably kept re-routing to the same
    # specialist to fetch the same answer again instead of picking FINISH —
    # prompt wording alone couldn't fully fix this non-determinism, so we
    # don't ask the LLM to reconfirm something we can already tell.
    # Exception: an email request whose content needs portfolio facts goes
    # portfolio_agent -> email_agent within the same turn, so the email uses
    # real numbers. Without this the finish rule below would end the turn
    # after portfolio_agent's answer. email_agent's own answer then finishes.
    if (
        state.get("next_agent") == "portfolio_agent"
        and isinstance(last, AIMessage)
        and not getattr(last, "tool_calls", None)
        and _EMAIL_REQUEST_RE.search(_latest_human_text(messages))
    ):
        return Command(
            goto="email_agent",
            update={"next_agent": "email_agent", "last_agent": "email_agent", "agent_hops": hops + 1},
        )

    if (
        state.get("next_agent") is not None
        and isinstance(last, AIMessage)
        and not getattr(last, "tool_calls", None)
    ):
        return _finish()

    # Deterministic sticky route: two rounds of prose/worked-example prompt
    # fixes both failed live re-testing -- the LLM router still sent a
    # "save it" follow-up to filesystem_agent instead of portfolio_agent,
    # producing a hand-typed .txt with no chart. Prompt wording alone isn't
    # reliable here, so -- like the FINISH-after-plain-answer rule above --
    # this is now decided in code: a fresh human turn that mentions
    # save/export/download, arriving right after portfolio_agent itself
    # OFFERED A REPORT, stays with portfolio_agent without asking the LLM.
    # Requiring the prior AIMessage to mention report/brief (not just
    # last_agent == portfolio_agent) matters: without it, "Save that my
    # investment horizon is 10 years" right after an unrelated portfolio
    # question would also stick to portfolio_agent, which has no
    # save_memory tool, and the fact would silently never get saved.
    if (
        hops == 0
        and isinstance(last, HumanMessage)
        and state.get("last_agent") == "portfolio_agent"
        and len(messages) >= 2
        and isinstance(messages[-2], AIMessage)
        and _REPORT_LANGUAGE_RE.search(_message_text(messages[-2]))
        and _SAVE_LANGUAGE_RE.search(_message_text(last))
    ):
        return Command(
            goto="portfolio_agent",
            update={"next_agent": "portfolio_agent", "last_agent": "portfolio_agent", "agent_hops": 1},
        )

    # NOTE: the conversation history already carries the user's question as
    # its first HumanMessage (record_question runs before this node), so we
    # don't re-inject it here. An earlier version did, and live QA showed the
    # duplicate "fresh-looking" question made the router think it was still
    # unanswered even right after a specialist gave a complete answer,
    # causing it to loop to MAX_AGENT_HOPS instead of picking FINISH.
    # with_structured_output is typed as dict | BaseModel; with a pydantic
    # schema it returns a RoutingDecision instance.
    # Substituted fresh on every call, not baked in at import time -- a PDF
    # uploaded via /data/import/pdf while the server is already running
    # must be recognized immediately, not only after a restart.
    routing_prompt = SUPERVISOR_ROUTING_PROMPT.replace(
        INGESTED_DOCUMENTS_PLACEHOLDER, ingested_documents_list()
    )
    # Without this, the router had no idea a client was even active (only
    # portfolio_agent/finance_agent/rag_agent read client_context via their
    # own client_context_prompt middleware) -- a vague client question like
    # "qui est le client" could route to memory_agent or another specialist
    # that has never heard of this client, producing a confused answer.
    client_context = state.get("client_context")
    if client_context:
        routing_prompt = (
            f"{routing_prompt}\n\n{client_context} When this client is active and the question "
            "is about them -- even phrased generically (\"who is the client\", \"what's their "
            "portfolio worth\") -- prefer portfolio_agent, finance_agent, or rag_agent over "
            "memory_agent/filesystem_agent/browser_agent/email_agent, which don't know who this "
            "client is."
        )
    decision = cast(RoutingDecision, _router.invoke(
        [
            SystemMessage(content=routing_prompt),
            *state.get("messages", []),
        ]
    ))

    next_agent = decision.next
    if next_agent == "FINISH":
        if _has_answer_to_latest_question(messages):
            return _finish()
        # Live QA showed the router returning FINISH on the first hop for
        # multi-specialist questions (its reasoning said "I need to route"),
        # ending the turn with no answer. Never finish unanswered — fall
        # back to the general-purpose specialist.
        next_agent = "rag_agent"

    return Command(
        goto=next_agent,
        update={"next_agent": next_agent, "last_agent": next_agent, "agent_hops": hops + 1},
    )


def _has_answer_to_latest_question(messages: list) -> bool:
    for m in reversed(messages):
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            return True
        if isinstance(m, HumanMessage):
            return False
    return False
