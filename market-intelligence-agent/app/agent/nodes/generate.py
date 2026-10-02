import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from app.core.config import settings
from app.agent.state import AgentState
from app.agent.tools import TOOLS
from app.agent.prompts import with_today
from app.agent.prompts.system import SYSTEM_PROMPT, ERROR_RECOVERY_PROMPT

logger = logging.getLogger(__name__)

_llm = ChatOpenAI(model=settings.OPENAI_MODEL, temperature=0, streaming=True)
# A transient OpenAI error (rate limit, timeout, 5xx) has nothing retrying it
# here -- unlike the multi-agent specialists' ModelRetryMiddleware, this graph
# calls the model directly with no middleware stack. with_retry() is the
# equivalent built into every LangChain Runnable; defaults (3 attempts,
# exponential backoff with jitter) match ModelRetryMiddleware's.
_llm_retry = _llm.with_retry()
_llm_with_tools = _llm.bind_tools(TOOLS).with_retry()

if settings.ANTHROPIC_API_KEY:
    # Same opt-in safety net as the multi-agent specialists'
    # model_fallback() (app/agent/middleware.py): with_fallbacks() is the
    # raw-Runnable equivalent of ModelFallbackMiddleware. Applied outside
    # with_retry() so OpenAI's own retries are exhausted first, same
    # retry-then-fallback ordering as the multi-agent middleware stack.
    from langchain_anthropic import ChatAnthropic

    _fallback_llm = ChatAnthropic(model="claude-sonnet-5-5", temperature=0)
    _llm_retry = _llm_retry.with_fallbacks([_fallback_llm.with_retry()])
    _llm_with_tools = _llm_with_tools.with_fallbacks(
        [_fallback_llm.bind_tools(TOOLS).with_retry()]
    )


def generate_answer(state: AgentState) -> dict:
    logger.info("GENERATE: Building response")
    messages = state.get("messages", [])

    if messages:
        last_message = messages[-1]
        if isinstance(last_message, ToolMessage) and getattr(last_message, "status", None) == "error":
            logger.warning("GENERATE: Tool error detected — generating explanation")
            return {
                "messages": [
                    _llm_retry.invoke([
                        SystemMessage(content=ERROR_RECOVERY_PROMPT),
                        HumanMessage(content=f"Technical error: {last_message.content}"),
                    ])
                ]
            }

    msgs = [SystemMessage(content=with_today(SYSTEM_PROMPT)), *messages]
    response = _llm_with_tools.invoke(msgs)
    return {"messages": [response]}
