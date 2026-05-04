from app.core.config import settings
from app.core.logging import configure_logging

configure_logging(settings.LOG_LEVEL)

from fastapi import FastAPI
from app.api.routers.chat import router as chat_router
from app.api.routers.health import router as health_router

app = FastAPI(title="Market Intelligence Agent API", version="0.1.0")
app.include_router(health_router)
app.include_router(chat_router)
