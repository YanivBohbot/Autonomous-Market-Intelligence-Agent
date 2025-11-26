from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv


load_dotenv()


class Settings(BaseSettings):
    # IA
    OPENAI_API_KEY: str
    OPENAI_MODEL: str
    OPENAI_EMBEDDING_MODEL: str

    # Pinecone
    PINECONE_API_KEY: str
    PINECONE_INDEX_NAME: str

    # tools
    TAVILY_API_KEY: str

    EMAIL_SENDER: str
    EMAIL_PASSWORD: str
    EMAIL_SMTP_SERVER: str
    EMAIL_SMTP_PORT: int

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
