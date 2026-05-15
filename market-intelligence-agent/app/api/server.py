from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI

from app.agent.graph import build_agent_app
from app.agent.memory.checkpointer import create_checkpointer
from app.agent.memory.store import create_store
from app.api.routers.approve import router as approve_router
from app.api.routers.health import router as health_router
from app.api.routers.livekit_token import router as livekit_token_router
from app.api.routers.stream import router as stream_router
from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL)


def _get_version() -> str:
    try:
        return _pkg_version("market-intelligence-agent")
    except PackageNotFoundError:
        return "0.0.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with create_checkpointer() as checkpointer:
        store = create_store()
        app.state.agent_app = build_agent_app(checkpointer, store)
        yield


app = FastAPI(
    title="Market Intelligence Agent API", version=_get_version(), lifespan=lifespan
)
app.include_router(health_router)
app.include_router(approve_router)
app.include_router(stream_router)
app.include_router(livekit_token_router)
