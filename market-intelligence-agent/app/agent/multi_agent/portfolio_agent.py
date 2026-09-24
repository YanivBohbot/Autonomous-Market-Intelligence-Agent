from langchain.agents import create_agent

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT
from app.agent.tools import (
    concentration_screen_tool,
    crm_describe_table_tool,
    crm_list_tables_tool,
    crm_tool,
    pct_change_tool,
    portfolio_metrics_tool,
    yf_quote_tool,
)

# Everything a portfolio computation needs lives in this one specialist: the
# supervisor finishes as soon as a specialist returns a plain answer, so
# chaining crm -> finance -> calc across specialists would not work.
_TOOLS = [
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    yf_quote_tool,
    portfolio_metrics_tool,
    pct_change_tool,
    concentration_screen_tool,
]


def build_portfolio_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=PORTFOLIO_SYSTEM_PROMPT,
        middleware=[*base_middleware()],
        name="portfolio_agent",
    )
