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

    msgs = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"User question: {question}\n\nDocument context (RAG):\n{context}"),
    ]
    if messages:
        msgs.extend(messages)

    response = _llm_with_tools.invoke(msgs)
    return {"messages": [response]}
