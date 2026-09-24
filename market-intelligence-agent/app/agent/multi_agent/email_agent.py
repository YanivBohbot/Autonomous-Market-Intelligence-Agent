from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import EMAIL_SYSTEM_PROMPT
from app.agent.tools import send_email_tool

_TOOLS = [send_email_tool]


def build_email_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=EMAIL_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"send_email": True}),
        ],
        name="email_agent",
    )
