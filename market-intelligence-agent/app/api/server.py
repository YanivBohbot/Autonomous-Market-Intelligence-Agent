from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import build_agent_app
from app.agent.memory.checkpointer import create_checkpointer
from app.agent.memory.store import create_store
from app.api.routers.agentcore import router as agentcore_router
from app.api.routers.approve import router as approve_router
from app.api.routers.health import router as health_router
from app.api.routers.stream import router as stream_router

# Voice / LiveKit is optional — the slim AgentCore image doesn't ship
# the `livekit` SDK. When absent, the /livekit/token endpoint just isn't
# mounted; everything else still works.
try:
    from app.api.routers.livekit_token import router as livekit_token_router
except ModuleNotFoundError:
    livekit_token_router = None
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
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)
app.include_router(health_router)
app.include_router(approve_router)
app.include_router(stream_router)
if livekit_token_router is not None:
    app.include_router(livekit_token_router)
app.include_router(agentcore_router)
