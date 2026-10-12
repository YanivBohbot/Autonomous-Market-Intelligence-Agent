import re
from typing import Any, Literal

from pydantic import BaseModel, Field
from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    dynamic_prompt,
)
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent.guardrails.card_guard import block_credit_cards
from app.agent.guardrails.detection import SENSITIVE_DATA_WARNING
from app.agent.middleware import (
    context_editing,
    fresh_documents_prompt,
    model_fallback,
    model_retry,
)
from app.core.config import settings
from app.agent.orchestration.state import ClientContextState, SupervisorState
from app.agent.prompts.orchestration_prompt import SUPERVISOR_ROUTING_PROMPT


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


# The routing decision is internal: Market Desk (ag-ui-langgraph streams via
# astream_events) must not render its JSON as chat text.
_ROUTER_MODEL_METADATA = {"emit-messages": False, "emit-tool-calls": False}


@dynamic_prompt
def client_context_routing_prompt(request: ModelRequest) -> str:
    """Without this, the router had no idea a client was even active (only
    portfolio_agent/finance_agent/rag_agent read client_context via their
    own client_context_prompt middleware) -- a vague client question like
    "qui est le client" could route to memory_agent or another specialist
    that has never heard of this client, producing a confused answer."""
    base = request.system_prompt or ""
    client_context = request.state.get("client_context")
    if not client_context:
        return base
    return (
        f"{base}\n\n{client_context} When this client is active and the question "
        'is about them -- even phrased generically ("who is the client", "what\'s their '
        'portfolio worth") -- prefer portfolio_agent, finance_agent, or rag_agent over '
        "memory_agent/filesystem_agent/browser_agent/email_agent, which don't know who this "
        "client is."
    )


_ROUTER_RESPONSE_FORMAT = ToolStrategy(RoutingDecision)
# Retries x model calls bound a failing router (3 x 3 attempts at most).
ROUTER_MODEL_CALL_LIMIT = 3


def build_router_agent(model: BaseChatModel | None = None):
    """The routing LLM call as a create_agent: structured output through
    response_format, plus the same official middleware the specialists get
    (card guard, live prompts, context editing, model retry/fallback).
    supervisor_node invokes it with a COPY of the conversation, so its own
    messages never enter the shared state (except the card guard's).

    No `name=`: it would set lc_agent_name, and ag-ui-langgraph would then
    stream the router as a subagent (SUBAGENT_STARTED, router steps) into
    Market Desk. `checkpointer=False`: a nested agent otherwise inherits the
    graph's checkpointer and writes a full conversation copy per call."""
    fallback = model_fallback()
    # Typed like base_middleware(): ModelCallLimitMiddleware carries its own
    # state type, and an inferred list type then matches no create_agent overload.
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        block_credit_cards,
        fresh_documents_prompt,
        client_context_routing_prompt,
        context_editing(),
        ModelCallLimitMiddleware(
            run_limit=ROUTER_MODEL_CALL_LIMIT, exit_behavior="error"
        ),
        *([fallback] if fallback is not None else []),
        model_retry(on_failure="error"),
    ]
    return create_agent(
        model=model
        or ChatOpenAI(
            model=settings.OPENAI_MODEL,
            temperature=0,
            model_kwargs={"parallel_tool_calls": False},
        ),
        tools=[],
        system_prompt=SUPERVISOR_ROUTING_PROMPT,
        response_format=_ROUTER_RESPONSE_FORMAT,
        state_schema=ClientContextState,
        middleware=middleware,
        checkpointer=False,
    )


router_agent = build_router_agent()

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
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content or "")


def supervisor_node(state: SupervisorState) -> Command[Route]:
    """The multi-agent supervisor node: route to a specialist or finalize the
    turn. The router agent is invoked with a COPY of the conversation, so its
    own messages never enter the shared state (except the card guard's)."""

    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    hops = 0 if isinstance(last, HumanMessage) else state.get("agent_hops", 0)
    if hops >= MAX_AGENT_HOPS:
        return _finish()

    if (
        state.get("next_agent") == "portfolio_agent"
        and isinstance(last, AIMessage)
        and not getattr(last, "tool_calls", None)
        and _EMAIL_REQUEST_RE.search(_latest_human_text(messages))
    ):
        return Command(
            goto="email_agent",
            update={
                "next_agent": "email_agent",
                "last_agent": "email_agent",
                "agent_hops": hops + 1,
            },
        )

    if (
        state.get("next_agent") is not None
        and isinstance(last, AIMessage)
        and not getattr(last, "tool_calls", None)
    ):
        return _finish()

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
            update={
                "next_agent": "portfolio_agent",
                "last_agent": "portfolio_agent",
                "agent_hops": 1,
            },
        )
    # Metadata on the invoke config is inherited by every model call inside
    # the router, the ModelFallbackMiddleware model included.
    # client_context is a ClientContextState field (state_schema); create_agent's
    # overloads only type the base InputAgentState, hence the cast.
    router_input: Any = {
        "messages": list(messages),
        "client_context": state.get("client_context"),
    }
    result = router_agent.invoke(
        router_input,
        {"metadata": _ROUTER_MODEL_METADATA},
    )
    decision = result.get("structured_response")
    if decision is None:
        last_message = result["messages"][-1] if result.get("messages") else None
        if getattr(last_message, "content", None) != SENSITIVE_DATA_WARNING:
            raise RuntimeError("Router agent ended without a routing decision.")
        # block_credit_cards ended the router run (@before_agent jump_to
        # "end"): carry its masked question (same id, so it replaces the raw
        # one) and its warning into the shared conversation, then end the turn.
        latest = next(
            (m for m in reversed(messages) if isinstance(m, HumanMessage)), None
        )
        carried = [
            m for m in result["messages"] if latest is not None and m.id == latest.id
        ]
        return Command(
            goto="finalize_turn",
            update={"messages": [*carried, result["messages"][-1]], "next_agent": None},
        )

    next_agent = decision.next
    if next_agent == "FINISH":
        if _has_answer_to_latest_question(messages):
            return _finish()

        next_agent = "rag_agent"

    return Command(
        goto=next_agent,
        update={
            "next_agent": next_agent,
            "last_agent": next_agent,
            "agent_hops": hops + 1,
        },
    )


def _has_answer_to_latest_question(messages: list) -> bool:
    for m in reversed(messages):
        if isinstance(m, AIMessage) and not getattr(m, "tool_calls", None):
            return True
        if isinstance(m, HumanMessage):
            return False
    return False
