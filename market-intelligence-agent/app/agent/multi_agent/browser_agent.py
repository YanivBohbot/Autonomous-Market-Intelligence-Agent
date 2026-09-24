from langchain.agents import create_agent

from app.agent.multi_agent.common import base_middleware, specialist_model, strip_tool_images
from app.agent.prompts.specialist_agent_prompts import BROWSER_SYSTEM_PROMPT
from app.agent.tools import browser_navigate_tool, browser_screenshot_tool, browser_snapshot_tool

_TOOLS = [browser_navigate_tool, browser_snapshot_tool, browser_screenshot_tool]


def build_browser_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=BROWSER_SYSTEM_PROMPT,
        middleware=[*base_middleware(), strip_tool_images],
        name="browser_agent",
    )
