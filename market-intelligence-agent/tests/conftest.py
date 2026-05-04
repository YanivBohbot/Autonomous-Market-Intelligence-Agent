import os
import pytest

# Set required env vars before any app imports so Settings() can be instantiated
# during test collection without a real .env file.
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("OPENAI_MODEL", "gpt-4o-mini")
os.environ.setdefault("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
os.environ.setdefault("PINECONE_API_KEY", "test-key")
os.environ.setdefault("PINECONE_INDEX_NAME", "test-index")
os.environ.setdefault("TAVILY_API_KEY", "test-key")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")
os.environ.setdefault("EMAIL_PASSWORD", "test-password")
os.environ.setdefault("EMAIL_SMTP_SERVER", "smtp.example.com")
os.environ.setdefault("EMAIL_SMTP_PORT", "587")


@pytest.fixture
def base_agent_state():
    return {
        "question": "What is Amazon's net revenue in 2024?",
        "documents": [],
        "messages": [],
    }
