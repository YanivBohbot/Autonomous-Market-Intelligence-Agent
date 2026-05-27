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
    EMAIL_SENDER: str = ""
    # Legacy SMTP credentials — no longer required after the move to Amazon
    # SES in prod (app/agent/tools/emails.py). Kept optional so local dev
    # .env files that still set them don't trip pydantic validation, and so
    # the simulation gate still has a string to inspect.
    EMAIL_PASSWORD: str = ""
    EMAIL_SMTP_SERVER: str = ""
    EMAIL_SMTP_PORT: int = 0
    # Voice mode (LiveKit + Deepgram + ElevenLabs) — only required when
    # the voice worker runs. The AgentCore text runtime never imports
    # app.voice.*, so defaults to "" keep the FastAPI app boot-able.
    LIVEKIT_URL: str = ""
    LIVEKIT_API_KEY: str = ""
    LIVEKIT_API_SECRET: str = ""
    DEEPGRAM_API_KEY: str = ""
    ELEVENLABS_API_KEY: str = ""
    LOG_LEVEL: str = "INFO"
    CHECKPOINTER_BACKEND: str = "sqlite"  # "sqlite" | "memory"
    CHECKPOINT_DB_PATH: str = "data/checkpoints.db"
    MCP_TRANSPORT: str = "stdio"  # "stdio" | "gateway"
    AGENTCORE_GATEWAY_URL: str = ""  # required when MCP_TRANSPORT=gateway
    WORKSPACE_BACKEND: str = "local"  # "local" | "s3" (consumed by the filesystem Lambda)
    WORKSPACE_S3_BUCKET: str = ""  # required when WORKSPACE_BACKEND=s3
    BROWSER_BACKEND: str = "local"  # "local" | "agentcore"
    BROWSER_TOOL_ID: str | None = None  # AgentCore Browser ARN, required when BROWSER_BACKEND=agentcore
    BROWSER_IDLE_TTL_S: int = 300
    API_URL: str = "http://127.0.0.1:8000"
    YFINANCE_TIMEOUT_S: int = 10
    WORKSPACE_ROOT: Path = Path("data/workspace")
    ELEVENLABS_VOICE_ID: str = "21m00Tcm4TlvDq8ikWAM"  # Rachel (ElevenLabs default voice)

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
