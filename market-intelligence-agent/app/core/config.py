from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

load_dotenv()


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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
