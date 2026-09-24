from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.multi_agent.common import base_middleware, specialist_model
from app.agent.prompts.specialist_agent_prompts import FILESYSTEM_SYSTEM_PROMPT
from app.agent.tools import fs_list_dir_tool, fs_read_file_tool, fs_write_file_tool

_TOOLS = [fs_read_file_tool, fs_list_dir_tool, fs_write_file_tool]


def build_filesystem_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=FILESYSTEM_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(),
            HumanInTheLoopMiddleware(interrupt_on={"write_file": True}),
        ],
        name="filesystem_agent",
    )
