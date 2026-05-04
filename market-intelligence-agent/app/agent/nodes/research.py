import logging
from tavily import TavilyClient
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def web_search(state: AgentState) -> dict:
    logger.info("WEB_SEARCH: Querying Tavily")
    question = state["question"]
    tavily = TavilyClient(api_key=settings.TAVILY_API_KEY)
    response = tavily.search(query=question, max_results=3, search_depth="advanced")
    web_results = [
        f"[SOURCE WEB: {r['url']}] {r['content']}"
        for r in response["results"]
    ]
    logger.info("WEB_SEARCH: Got %d results", len(web_results))
    return {"documents": web_results}
