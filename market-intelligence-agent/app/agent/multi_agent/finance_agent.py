from langchain.agents import create_agent

from app.agent.multi_agent.common import base_middleware, redact_emails, specialist_model
from app.agent.prompts.specialist_agent_prompts import FINANCE_SYSTEM_PROMPT
from app.agent.tools import yf_history_tool, yf_news_tool, yf_quote_tool

_TOOLS = [yf_quote_tool, yf_history_tool, yf_news_tool]


def build_finance_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=FINANCE_SYSTEM_PROMPT,
        # Queries go to third parties (Tavily / Yahoo / web pages): no addresses.
        middleware=[*base_middleware(), redact_emails()],
        name="finance_agent",
    )
