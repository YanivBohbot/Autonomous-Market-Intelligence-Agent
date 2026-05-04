import logging
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from app.core.config import settings
from app.agent.state import AgentState

logger = logging.getLogger(__name__)


def retriveal_internal_documention(state: AgentState) -> dict:
    logger.info("RAG: Starting internal document search")
    question = state["question"]
    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    vectorstore = PineconeVectorStore(
        index_name=settings.PINECONE_INDEX_NAME, embedding=embeddings
    )
    docs = vectorstore.similarity_search(question, k=3)
    content = [f"[INTERNAL Resource] {d.page_content}" for d in docs]
    logger.info("RAG: Retrieved %d chunks", len(content))
    return {"documents": content}
