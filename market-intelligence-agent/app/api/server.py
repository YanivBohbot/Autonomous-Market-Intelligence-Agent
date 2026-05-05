from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL)

from contextlib import asynccontextmanager
from importlib.metadata import version as _pkg_version, PackageNotFoundError
from fastapi import FastAPI
from app.agent.graph import agent_app
from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router


def _get_version() -> str:
    try:
        return _pkg_version("market-intelligence-agent")
    except PackageNotFoundError:
        return "0.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    checkpointer = agent_app.checkpointer
    if hasattr(checkpointer, "conn") and checkpointer.conn:
        checkpointer.conn.close()


app = FastAPI(title="Market Intelligence Agent API", version=_get_version(), lifespan=lifespan)
app.include_router(health_router)
app.include_router(chat_router)
