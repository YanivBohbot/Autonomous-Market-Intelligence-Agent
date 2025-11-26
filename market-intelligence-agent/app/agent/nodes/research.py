from tavily import TavilyClient
from app.core.config import settings
from app.agent.state import AgentState


def web_search(state: AgentState):
    print("🌐 [NODE] WEB: Recherche internet...")
    question = state["question"]

    tavily = TavilyClient(api_key=settings.TAVILY_API_KEY)
    response = tavily.search(query=question, max_results=3, search_depth="advanced")

    web_results = []
    for result in response["results"]:
        web_results.append(f"[SOURCE WEB: {result['url']}] {result['content']}")

    return {"documents": web_results}
