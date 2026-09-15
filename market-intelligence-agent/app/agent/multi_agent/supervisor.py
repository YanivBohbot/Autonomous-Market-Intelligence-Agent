from typing import Literal

from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, AIMessage
from langgraph.types import Command
from langgraph.graph import END

from app.core.config import settings
from app.agent.multi_agent.state import SupervisorState
from app.agent.prompts.specialist_agent_prompts import SUPERVISOR_ROUTING_PROMPT


class RoutingDecision(BaseModel):
    next: Literal[
        "rag_agent",
        "finance_agent",
        "crm_agent",
        "memory_agent",
        "filesystem_agent",
        "browser_agent",
        "email_agent",
        "FINISH",
    ] = Field(
        description="Which specialist should act next, or FINISH if the "
        "conversation already has a complete answer to the user's question."
    )
    reasoning: str = Field(description="One sentence: why this specialist (or FINISH).")


_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0)
_router = _llm.with_structured_output(RoutingDecision)

MAX_AGENT_HOPS = 4


def supervisor_node(
    state: SupervisorState,
) -> Command[
    Literal[
        "rag_agent",
        "finance_agent",
        "crm_agent",
        "memory_agent",
        "filesystem_agent",
        "browser_agent",
        "email_agent",
        "__end__",
    ]
]:
    hops = state.get("agent_hops", 0)
    if hops >= MAX_AGENT_HOPS:
        return Command(goto=END, update={"next_agent": None})

    # Deterministic finish: once a specialist hands control back with a
    # plain completed answer (no further tool_calls), the turn is done.
    # Live QA showed the LLM router unreliably kept re-routing to the same
    # specialist to fetch the same answer again instead of picking FINISH —
    # prompt wording alone couldn't fully fix this non-determinism, so we
    # don't ask the LLM to reconfirm something we can already tell.
    messages = state.get("messages", [])
    last = messages[-1] if messages else None
    if (
        state.get("next_agent") is not None
        and isinstance(last, AIMessage)
        and not getattr(last, "tool_calls", None)
    ):
        return Command(goto=END, update={"next_agent": None})

    # NOTE: the conversation history already carries the user's question as
    # its first HumanMessage (record_question runs before this node), so we
    # don't re-inject it here. An earlier version did, and live QA showed the
    # duplicate "fresh-looking" question made the router think it was still
    # unanswered even right after a specialist gave a complete answer,
    # causing it to loop to MAX_AGENT_HOPS instead of picking FINISH.
    decision = _router.invoke(
        [
            SystemMessage(content=SUPERVISOR_ROUTING_PROMPT),
            *state.get("messages", []),
        ]
    )

    if decision.next == "FINISH":
        return Command(goto=END, update={"next_agent": None})

    return Command(
        goto=decision.next,
        update={"next_agent": decision.next, "agent_hops": hops + 1},
    )
