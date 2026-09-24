from langchain.agents import create_agent

from app.agent.multi_agent.common import base_middleware, redact_emails, specialist_model
from app.agent.prompts.specialist_agent_prompts import RAG_SYSTEM_PROMPT
from app.agent.tools import search_knowledge_base_tool, web_search_tool

_TOOLS = [search_knowledge_base_tool, web_search_tool]


def build_rag_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=RAG_SYSTEM_PROMPT,
        # Queries go to third parties (Tavily / Yahoo / web pages): no addresses.
        middleware=[*base_middleware(), redact_emails()],
        name="rag_agent",
    )
