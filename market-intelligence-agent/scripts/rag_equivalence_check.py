"""Print search_knowledge_base output for fixed queries as JSON, to compare
retrieval before and after the app/rag/ refactor. Calls the tool directly
(deterministic: vector search + Pinecone rerank, no LLM)."""
import json
import sys

from app.agent.tools.knowledge_base import search_knowledge_base_tool

QUERIES = [
    {"query": "What does Amazon say about AI in its 2024 annual report?", "k": 4},
    {"query": "Amazon total net sales 2024", "k": 4, "source_filter": "Amazon"},
    {"query": "best chocolate cake recipe", "k": 4},
    {"query": "revenue", "k": 3, "source_filter": "NoSuchCompany"},
]

if __name__ == "__main__":
    out = {q["query"]: search_knowledge_base_tool.invoke(q) for q in QUERIES}
    json.dump(out, sys.stdout, indent=2, ensure_ascii=False)
