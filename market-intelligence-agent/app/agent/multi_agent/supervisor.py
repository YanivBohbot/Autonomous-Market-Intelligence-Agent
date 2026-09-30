import re
from typing import Literal, cast

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage, HumanMessage
from langgraph.types import Command

from app.core.config import settings
from app.agent.multi_agent.state import SupervisorState
from app.agent.prompts.specialist_agent_prompts import SUPERVISOR_ROUTING_PROMPT


SpecialistName = Literal[
    "rag_agent",
    "finance_agent",
    "portfolio_agent",
    "memory_agent",
    "filesystem_agent",
    "browser_agent",
    "email_agent",
]
# Where the supervisor can send control: a specialist, or END ("__end__").
Route = Literal[SpecialistName, "__end__"]


def _finish() -> Command[Route]:
    # "__end__" is langgraph's END; spelled as a literal so the type checker
    # keeps Command[Route] instead of widening to Command[str].
    return Command(goto="__end__", update={"next_agent": None})


class RoutingDecision(BaseModel):
    next: SpecialistName | Literal["FINISH"] = Field(
        description="Which specialist should act next, or FINISH if the "
        "conversation already has a complete answer to the user's question."
    )
    reasoning: str = Field(description="One sentence: why this specialist (or FINISH).")


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
    # save/export/download, arriving right after portfolio_agent itself last
    # answered, stays with portfolio_agent without asking the LLM.
    if (
        hops == 0
        and isinstance(last, HumanMessage)
        and state.get("last_agent") == "portfolio_agent"
        and _SAVE_LANGUAGE_RE.search(last.content or "")
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
    decision = cast(RoutingDecision, _router.invoke(
        [
            SystemMessage(content=SUPERVISOR_ROUTING_PROMPT),
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
