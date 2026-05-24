import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.core.config import settings
from app.agent.state import AgentState
from app.agent.tools import TOOLS
from app.agent.prompts.system import SYSTEM_PROMPT, ERROR_RECOVERY_PROMPT

logger = logging.getLogger(__name__)

_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)
_llm_with_tools = _llm.bind_tools(TOOLS)


def generate_answer(state: AgentState) -> dict:
    logger.info("GENERATE: Building response")
    question = state["question"]
    documents = state["documents"]
    messages = state.get("messages", [])
    context = "\n\n".join(documents)

    if messages:
        last_message = messages[-1]
        if isinstance(last_message, ToolMessage) and getattr(last_message, "status", None) == "error":
            logger.warning("GENERATE: Tool error detected — generating explanation")
            return {
                "messages": [
                    _llm.invoke([
                        SystemMessage(content=ERROR_RECOVERY_PROMPT),
                        HumanMessage(content=f"Technical error: {last_message.content}"),
                    ])
                ]
            }

    # Prompt-caching contract (OpenAI auto-caches prefixes >=1024 tokens, cuts
    # input-token cost ~50% on cache hits):
    #   1. The system prompt is byte-identical across requests — put it first.
    #   2. The tool schemas bound via .bind_tools() are also static prefix.
    #   3. The per-turn variable parts (user question, RAG docs, prior turns)
    #      go AFTER the static prefix so the cacheable prefix stays stable.
    # Do not interpolate request-specific data into SYSTEM_PROMPT or you break
    # the cache. See prod/SPEC.md §5.5 optimization #1.
    msgs = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"User question: {question}\n\nDocument context (RAG):\n{context}"),
    ]
    if messages:
        msgs.extend(messages)

    response = _llm_with_tools.invoke(msgs)
    return {"messages": [response]}
