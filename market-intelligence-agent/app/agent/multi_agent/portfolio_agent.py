from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.multi_agent.display import market_desk_display
from app.agent.prompts.specialist_agent_prompts import PORTFOLIO_SYSTEM_PROMPT
from app.agent.tools import (
    client_portfolio_tool,
    concentration_screen_tool,
    crm_describe_table_tool,
    crm_list_tables_tool,
    crm_tool,
    fs_write_file_tool,
    generate_portfolio_report_tool,
    pct_change_tool,
    portfolio_metrics_tool,
    yf_quote_tool,
)

# Everything a portfolio computation needs lives in this one specialist: the
# supervisor finishes as soon as a specialist returns a plain answer, so
# chaining crm -> finance -> calc across specialists would not work. Same
# reasoning extends to write_file: portfolio_agent needs it directly so
# "generate a report, then save it" happens in one turn, not a two-hop
# handoff to filesystem_agent that depends on the router recognizing the
# answer as incomplete.
_TOOLS = [
    crm_tool,
    crm_list_tables_tool,
    crm_describe_table_tool,
    yf_quote_tool,
    portfolio_metrics_tool,
    pct_change_tool,
    concentration_screen_tool,
    client_portfolio_tool,
    generate_portfolio_report_tool,
    fs_write_file_tool,
]


def build_portfolio_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=PORTFOLIO_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"write_file": True}),
            market_desk_display,
        ],
        name="portfolio_agent",
    )
