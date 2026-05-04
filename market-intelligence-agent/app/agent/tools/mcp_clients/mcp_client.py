import asyncio
import logging
import os
from contextlib import AsyncExitStack
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from langchain_core.tools import Tool

logger = logging.getLogger(__name__)

server_params = StdioServerParameters(
    command="uv",
    args=["run", "mcp-server-sqlite", "--db-path", "customers.db"],
    env=os.environ,
)


async def query_crm_tool(query: str) -> str:
    logger.info("MCP: Executing CRM query: %.80s", query)
    try:
        async with AsyncExitStack() as stack:
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(server_params)
            )
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()
            result = await session.call_tool("read_query", arguments={"query": query})
            if result.content and len(result.content) > 0:
                return result.content[0].text
            return "Aucun résultat trouvé."
    except Exception as e:
        logger.error("MCP: Error — %s", e)
        return f"Erreur MCP : {str(e)}"


def sync_query_wrapper(query: str) -> str:
    try:
        return asyncio.run(query_crm_tool(query))
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(query_crm_tool(query))
        finally:
            loop.close()


crm_tool = Tool(
    name="crm_query",
    func=sync_query_wrapper,
    description="Exécute une requête SQL SELECT sur la base clients (table: customers). Colonnes: id, name, email, status, total_spend.",
)
