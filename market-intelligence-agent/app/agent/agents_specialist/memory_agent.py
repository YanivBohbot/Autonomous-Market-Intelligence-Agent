from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware

from app.agent.middleware import base_middleware, specialist_model
from app.agent.prompts.agents_specialist_prompts import MEMORY_SYSTEM_PROMPT
from app.agent.tools import list_memories_tool, recall_memory_tool, save_memory_tool

_TOOLS = [save_memory_tool, recall_memory_tool, list_memories_tool]


def build_memory_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=MEMORY_SYSTEM_PROMPT,
        middleware=[
            *base_middleware(_TOOLS),
            HumanInTheLoopMiddleware(interrupt_on={"save_memory": True}),
        ],
        name="memory_agent",
    )
