from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from app.core.config import settings
from app.agent.state import AgentState


def retriveal_internal_documention(state: AgentState):
    print("📚 [NODE] RAG: Recherche interne...")
    question = state["question"]

    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)
    vectorstore = PineconeVectorStore(
        index_name=settings.PINECONE_INDEX_NAME, embedding=embeddings
    )

    docs = vectorstore.similarity_search(question, k=3)
    content = [f"[INTERNAL Resource] {d.page_content}" for d in docs]

    return {"documents": content}
