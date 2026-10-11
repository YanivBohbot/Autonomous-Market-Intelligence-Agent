from langchain.agents import create_agent

from app.agent.middleware import base_middleware, client_context_prompt, fresh_documents_prompt, redact_emails, specialist_model, tool_call_limit
from app.agent.multi_agent.display import market_desk_display
from app.agent.multi_agent.state import ClientContextState
from app.agent.prompts.specialist_agent_prompts import RAG_SYSTEM_PROMPT
from app.agent.tools import search_knowledge_base_tool, web_search_tool

_TOOLS = [search_knowledge_base_tool, web_search_tool]


def build_rag_agent():
    return create_agent(
        model=specialist_model(),
        tools=_TOOLS,
        system_prompt=RAG_SYSTEM_PROMPT,
        state_schema=ClientContextState,
        # Queries go to third parties (Tavily / Yahoo / web pages): no addresses.
        # fresh_documents_prompt substitutes the live manifest in at call
        # time -- RAG_SYSTEM_PROMPT itself only carries the placeholder.
        middleware=[*base_middleware(_TOOLS), redact_emails(), tool_call_limit("web_search", 3), fresh_documents_prompt, client_context_prompt, market_desk_display],
        name="rag_agent",
    )
