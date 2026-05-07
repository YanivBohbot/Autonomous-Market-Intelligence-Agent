from pathlib import Path
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

env_file = Path(__file__).parent.parent.parent / ".env"
load_dotenv(env_file)


class Settings(BaseSettings):
    OPENAI_API_KEY: str
    OPENAI_MODEL: str
    OPENAI_EMBEDDING_MODEL: str
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str
    TAVILY_API_KEY: str
    EMAIL_SENDER: str
    EMAIL_PASSWORD: str
    EMAIL_SMTP_SERVER: str
    EMAIL_SMTP_PORT: int
    LOG_LEVEL: str = "INFO"
    CHECKPOINT_DB_PATH: str = "data/checkpoints.db"
    API_URL: str = "http://127.0.0.1:8000"
    YFINANCE_TIMEOUT_S: int = 10

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
