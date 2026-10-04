from langchain.agents import create_agent

from app.agent.middleware import (
    base_middleware,
    client_context_prompt,
    redact_emails,
    specialist_model,
)
from app.agent.multi_agent.display import market_desk_display
from app.agent.multi_agent.state import ClientContextState
from app.agent.prompts.specialist_agent_prompts import FINANCE_SYSTEM_PROMPT
from app.agent.tools import yf_history_tool, yf_news_tool, yf_quote_tool

_TOOLS = [yf_quote_tool, yf_history_tool, yf_news_tool]


def build_finance_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=FINANCE_SYSTEM_PROMPT,
        state_schema=ClientContextState,
        middleware=[*base_middleware(), redact_emails(), client_context_prompt, market_desk_display],
        name="finance_agent",
    )
