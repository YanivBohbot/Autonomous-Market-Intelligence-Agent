from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.common import base_middleware, specialist_model
from app.agent.multi_agent.display import market_desk_display
from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT
from app.agent.tools import (
    client_portfolio_tool,
    concentration_screen_tool,
    crm_describe_table_tool,
    crm_list_tables_tool,
    crm_tool,
    pct_change_tool,
    portfolio_metrics_tool,
    save_portfolio_report_tool,
    yf_quote_tool,
)

# Everything a portfolio computation needs lives in this one specialist: the
# supervisor finishes as soon as a specialist returns a plain answer, so
# chaining crm -> finance -> calc across specialists would not work.
# save_portfolio_report_tool loads, builds, and writes the report itself in
# one atomic call -- no write_file, no chaining to filesystem_agent, and
# nothing content-shaped for the LLM to touch.
_TOOLS = [
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    yf_quote_tool,
    portfolio_metrics_tool,
    pct_change_tool,
    concentration_screen_tool,
    client_portfolio_tool,
    save_portfolio_report_tool,
]


def build_portfolio_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=PORTFOLIO_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"save_portfolio_report": True}),
            market_desk_display,
        ],
        name="portfolio_agent",
    )
