import asyncio
import os
import sys
from contextlib import AsyncExitStack

# Imports MCP
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Import LangChain
from langchain_core.tools import Tool

# Configuration du serveur
server_params = StdioServerParameters(
    command="uv",
    args=["run", "mcp-server-sqlite", "--db-path", "customers.db"],
    env=os.environ,
)


async def query_crm_tool(query: str):
    """
    Fonction asynchrone qui parle au serveur MCP.
    """
    print(f"🔌 [MCP] Connexion au serveur CRM pour exécuter : {query}")

    try:
        async with AsyncExitStack() as stack:
            # 1. Lancement du serveur et récupération des flux (Lecture/Écriture)
            # CORRECTION ICI : On sépare read_stream et write_stream
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(server_params)
            )

            # 2. Initialisation de la session avec les flux séparés
            session = await stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await session.initialize()

            # 3. Appel de l'outil
            result = await session.call_tool("read_query", arguments={"query": query})

            if result.content and len(result.content) > 0:
                return result.content[0].text
            return "Aucun résultat trouvé."

    except Exception as e:
        return f"Erreur MCP : {str(e)}"


def sync_query_wrapper(query: str):
    try:
        return asyncio.run(query_crm_tool(query))
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(query_crm_tool(query))


crm_tool = Tool(
    name="crm_query",
    func=sync_query_wrapper,
    description="Exécute une requête SQL SELECT sur la base clients (table: customers). Colonnes: id, name, email, status, total_spend.",
)

if __name__ == "__main__":
    # Test direct
    print(crm_tool.invoke("SELECT * FROM customers "))
